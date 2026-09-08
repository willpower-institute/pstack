"""🔒 Kernel public-surface contract — conformance gate

kernel เปิด symbol ชุดหนึ่งให้ consumer app (care, vdo, vituntasa, …) และ addon
พึ่งพา ถ้า symbol หาย / เปลี่ยนชื่อ param / ลบ param โดยไม่ตั้งใจ → consumer พังเงียบ
ตอน deploy เทสนี้จับ drift ก่อนถึงมือ consumer โดยเทียบ surface จริงกับ snapshot ที่
commit ไว้ที่ contract/kernel-contract.json

เพิ่ม/ลบ symbol สาธารณะ = แก้ SURFACE ข้างล่าง · เปลี่ยน signature โดยตั้งใจ = แก้โค้ด
ทั้งสองกรณีให้ re-sync snapshot แล้ว review diff:

    PSTACK_UPDATE_CONTRACT=1 pytest tests/test_kernel_contract.py

แล้วบันทึกการเปลี่ยนใน CHANGELOG (breaking ต่อ consumer ต้องขึ้นเวอร์ชันตาม semver)

หมายเหตุ: เทสนี้ล็อก **รูปร่าง** ของ surface (มี symbol ไหน, param ชื่ออะไร) ส่วนการล็อก
**ค่า** ข้าม repo (เช่น regex ของ ID_PATTERN ที่ต้องตรง identity/v1) ยังเป็นหน้าที่ของเทส
เฉพาะทางอย่าง test_tenancy.py::test_id_pattern_is_identity_v1_contract
"""

import importlib
import inspect
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

CONTRACT_PATH = (
    pathlib.Path(__file__).resolve().parents[1] / "contract" / "kernel-contract.json"
)
CONTRACT_VERSION = 1

# 🔒 public surface — symbol ที่ consumer/addon พึ่งพา (มาจากการ grep import จริงใน addons/)
# แก้ dict นี้เฉพาะเมื่อจะ "เพิ่ม" หรือ "เลิกรองรับ" symbol สาธารณะ
SURFACE: dict[str, list[str]] = {
    "core.app": ["create_app"],
    "core.config": ["get_settings"],
    "core.db": ["Base", "get_session", "get_sessionmaker", "dispose_engine"],
    "core.auth": [
        "get_current_user",
        "require_permission",
        "create_access_token",
        "decode_access_token",
        "hash_password",
        "verify_password",
    ],
    "core.tenancy": [
        "ID_PATTERN",
        "validate_id",
        "new_id",
        "InvalidId",
        "Principal",
        "TenantScope",
        "scoped",
        "bind_tenant",
        "TenantIsolationError",
    ],
    "core.templating": ["render"],
    "core.ai": ["agent_tool", "get_tools"],
    "core.ratelimit": ["RateLimited", "check_rate_limit", "client_ip"],
    "core.jobs": ["background_job"],
    "core.registry": ["installed_modules"],
    "core.runtime": ["ctx"],
    "core.clock": ["now", "set_now", "FakeClock"],
}

_MISSING = object()


def _params(obj: object) -> list[str] | None:
    """ชื่อ param ตามลำดับ · เติม '?' ถ้ามี default, '*'/'**' สำหรับ var-args
    (จับ rename/ลบ/ทำให้บังคับ/เพิ่ม param ได้ · ไม่ผูกกับ type annotation → เสถียรข้าม Python version)
    """
    try:
        sig = inspect.signature(obj)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return None  # เช่น exception class ที่ introspect signature ไม่ได้
    out: list[str] = []
    for p in sig.parameters.values():
        if p.name == "self":
            continue
        if p.kind is p.VAR_POSITIONAL:
            out.append("*" + p.name)
        elif p.kind is p.VAR_KEYWORD:
            out.append("**" + p.name)
        elif p.default is not p.empty:
            out.append(p.name + "?")
        else:
            out.append(p.name)
    return out


def _describe(obj: object) -> dict[str, object]:
    if not inspect.isclass(obj) and not callable(obj):
        return {"kind": "constant", "type": type(obj).__name__}
    kind = "class" if inspect.isclass(obj) else "function"
    params = _params(obj)
    return {"kind": kind, "params": params if params is not None else []}


def build_actual() -> dict[str, object]:
    """surface จริงของ kernel ณ ตอนนี้ (import แต่ละโมดูลแล้ว introspect)"""
    symbols: dict[str, dict[str, object]] = {}
    for mod_name, names in SURFACE.items():
        module = importlib.import_module(mod_name)  # ImportError = โมดูลพัง → ปล่อยให้ raise
        entry: dict[str, object] = {}
        for name in names:
            obj = getattr(module, name, _MISSING)
            entry[name] = {"kind": "missing"} if obj is _MISSING else _describe(obj)
        symbols[mod_name] = entry
    return {"version": CONTRACT_VERSION, "symbols": symbols}


def _dumps(contract: dict[str, object]) -> str:
    return json.dumps(contract, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _flatten(contract: dict) -> dict[str, str]:
    """{'core.app.create_app': 'function(params=[])'} — สำหรับข้อความ diff ที่อ่านง่าย"""
    flat: dict[str, str] = {}
    for mod_name, entry in contract.get("symbols", {}).items():
        for name, desc in entry.items():
            if desc.get("kind") == "constant":
                sig = f"constant<{desc.get('type')}>"
            else:
                sig = f"{desc.get('kind')}(params={desc.get('params')})"
            flat[f"{mod_name}.{name}"] = sig
    return flat


def _diff_message(actual: dict, expected: dict) -> str:
    a, e = _flatten(actual), _flatten(expected)
    lines = ["kernel public surface เปลี่ยนจาก snapshot ที่ commit ไว้:"]
    for key in sorted(set(e) - set(a)):
        lines.append(f"  - หาย/เปลี่ยน symbol: {key}  (snapshot: {e[key]})")
    for key in sorted(set(a) - set(e)):
        lines.append(f"  + symbol ใหม่ที่ยังไม่อยู่ใน snapshot: {key}  ({a[key]})")
    for key in sorted(set(a) & set(e)):
        if a[key] != e[key]:
            lines.append(f"  ~ signature เปลี่ยน: {key}\n      snapshot: {e[key]}\n      ตอนนี้:   {a[key]}")
    lines.append("")
    lines.append("ถ้าเป็นการเปลี่ยนโดยตั้งใจ: PSTACK_UPDATE_CONTRACT=1 pytest tests/test_kernel_contract.py")
    lines.append("แล้ว review diff ของ contract/kernel-contract.json + บันทึกใน CHANGELOG (breaking = ขึ้นเวอร์ชัน)")
    return "\n".join(lines)


def test_kernel_contract_matches_snapshot():
    actual = build_actual()

    if os.environ.get("PSTACK_UPDATE_CONTRACT"):
        CONTRACT_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONTRACT_PATH.write_text(_dumps(actual), encoding="utf-8")
        return  # โหมด re-sync — เขียน snapshot ใหม่แล้วผ่าน (diff คือสิ่งที่ต้อง review)

    assert CONTRACT_PATH.exists(), (
        f"ไม่พบ snapshot ที่ {CONTRACT_PATH} — สร้างครั้งแรกด้วย "
        "PSTACK_UPDATE_CONTRACT=1 pytest tests/test_kernel_contract.py"
    )
    expected = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    assert actual == expected, _diff_message(actual, expected)
