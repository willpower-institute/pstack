"""Smoke test — บูตทั้งระบบบน sqlite: loader -> install -> auth -> RBAC -> tools"""

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

os.environ["PSTACK_DATABASE_URL"] = "sqlite+aiosqlite:///./test_pstack.db"
os.environ["PSTACK_SECRET_KEY"] = "test-secret"
os.environ["PSTACK_MODULES"] = "users,storage,ai_agent,line_oa,faq,api_keys,mcp_server,extdemo"
os.environ["PSTACK_ADDONS_PATHS"] = "addons,tests/ext_addons"  # ทดสอบ external addons path
os.environ["PSTACK_STORAGE_DIR"] = "./test_uploads"
os.environ["PSTACK_LINE_SYNC_MODE"] = "true"  # ประมวลผล webhook แบบ sync ในเทส

import pytest
from fastapi.testclient import TestClient

from core.app import create_app


@pytest.fixture(scope="module")
def client():
    import shutil

    db_file = pathlib.Path("./test_pstack.db")
    uploads = pathlib.Path("./test_uploads")
    if db_file.exists():
        db_file.unlink()
    if uploads.exists():
        shutil.rmtree(uploads)
    app = create_app()
    with TestClient(app) as c:
        yield c
    if db_file.exists():
        db_file.unlink()
    if uploads.exists():
        shutil.rmtree(uploads)


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert "users" in r.json()["modules"]


def test_login_and_me(client):
    r = client.post(
        "/api/auth/login", json={"email": "admin@example.com", "password": "admin"}
    )
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]

    r = client.get("/api/users/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["email"] == "admin@example.com"
    assert r.json()["is_superuser"] is True


def test_rbac_and_create_user(client):
    token = client.post(
        "/api/auth/login", json={"email": "admin@example.com", "password": "admin"}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # superuser สร้าง user ใหม่ได้
    r = client.post(
        "/api/users",
        json={"email": "somchai@example.com", "password": "pw1234", "full_name": "สมชาย"},
        headers=headers,
    )
    assert r.status_code == 201, r.text

    # user ใหม่ไม่มี role -> list users ต้องโดน 403
    user_token = client.post(
        "/api/auth/login", json={"email": "somchai@example.com", "password": "pw1234"}
    ).json()["access_token"]
    r = client.get("/api/users", headers={"Authorization": f"Bearer {user_token}"})
    assert r.status_code == 403

    # ไม่มี token -> 401
    assert client.get("/api/users/me").status_code == 401


def test_storage_flow(client):
    token = client.post(
        "/api/auth/login", json={"email": "admin@example.com", "password": "admin"}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # upload
    r = client.post(
        "/api/storage/upload",
        files={"file": ("hello.txt", b"pstack file content", "text/plain")},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    file_id = r.json()["id"]
    assert r.json()["original_name"] == "hello.txt"

    # list
    r = client.get("/api/storage", headers=headers)
    assert any(f["id"] == file_id for f in r.json())

    # download — เนื้อไฟล์ต้องตรง
    r = client.get(f"/api/storage/{file_id}/download", headers=headers)
    assert r.status_code == 200
    assert r.content == b"pstack file content"

    # คนอื่น (non-superuser) เข้าถึงไฟล์เราไม่ได้
    other_token = client.post(
        "/api/auth/login", json={"email": "somchai@example.com", "password": "pw1234"}
    ).json()["access_token"]
    r = client.get(
        f"/api/storage/{file_id}/download",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert r.status_code == 403

    # delete
    r = client.delete(f"/api/storage/{file_id}", headers=headers)
    assert r.status_code == 204
    r = client.get(f"/api/storage/{file_id}/download", headers=headers)
    assert r.status_code == 404


class FakeStream:
    """แทน anthropic streaming context — script การตอบของโมเดลทีละ turn"""

    def __init__(self, deltas, final):
        self._deltas = deltas
        self._final = final

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    @property
    def text_stream(self):
        async def gen():
            for d in self._deltas:
                yield d

        return gen()

    async def get_final_message(self):
        return self._final


def test_agent_session_and_tools(client):
    token = client.post(
        "/api/auth/login", json={"email": "admin@example.com", "password": "admin"}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    r = client.post("/api/agent/sessions", json={"title": ""}, headers=headers)
    assert r.status_code == 201
    assert client.get("/api/agent/sessions", headers=headers).json()

    # superuser เห็น tools ของโมดูล users
    tools = client.get("/api/agent/tools", headers=headers).json()
    names = {t["name"] for t in tools}
    assert {"count_users", "search_users"} <= names


def test_agent_chat_with_tool(client, monkeypatch):
    from types import SimpleNamespace

    from addons.ai_agent.runtime import AgentRuntime

    # turn 1: โมเดลขอเรียก count_users, turn 2: ตอบ text จบ
    turns = [
        FakeStream(
            [],
            SimpleNamespace(
                content=[
                    {"type": "tool_use", "id": "tu_1", "name": "count_users", "input": {}}
                ],
                stop_reason="tool_use",
            ),
        ),
        FakeStream(
            ["มีผู้ใช้ ", "2 คนครับ"],
            SimpleNamespace(
                content=[{"type": "text", "text": "มีผู้ใช้ 2 คนครับ"}],
                stop_reason="end_turn",
            ),
        ),
    ]
    monkeypatch.setattr(
        AgentRuntime, "_stream_ctx", lambda self, *, system, messages, tools: turns.pop(0)
    )

    token = client.post(
        "/api/auth/login", json={"email": "admin@example.com", "password": "admin"}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    sid = client.post("/api/agent/sessions", json={}, headers=headers).json()["id"]
    r = client.post(
        f"/api/agent/sessions/{sid}/messages",
        json={"text": "ตอนนี้มีผู้ใช้กี่คน"},
        headers=headers,
    )
    assert r.status_code == 200
    body = r.text
    assert '"tool_use"' in body and '"count_users"' in body   # เรียก tool จริง
    assert '"tool_result"' in body and '"ok": true' in body   # tool รันสำเร็จ
    assert '"done"' in body

    # ประวัติถูกเก็บ: ข้อความ user + คำตอบ assistant (แถว tool ไม่โชว์)
    msgs = client.get(f"/api/agent/sessions/{sid}/messages", headers=headers).json()
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["text"] == "มีผู้ใช้ 2 คนครับ"

    # session title ถูกตั้งจากข้อความแรก
    sessions = client.get("/api/agent/sessions", headers=headers).json()
    assert any(s["title"] == "ตอนนี้มีผู้ใช้กี่คน" for s in sessions)


def _line_sign(secret: str, body: bytes) -> str:
    import base64
    import hashlib
    import hmac

    return base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()


def _line_post(client, channel_id, secret, payload):
    body = json.dumps(payload).encode()
    return client.post(
        f"/api/line/webhook/{channel_id}",
        content=body,
        headers={
            "x-line-signature": _line_sign(secret, body),
            "content-type": "application/json",
        },
    )


import json


@pytest.fixture(scope="module")
def line_capture(client):
    """สร้าง LINE channel + ดัก reply/push แทนการยิง LINE API จริง"""
    import addons.line_oa.client as line_client

    captured = {"reply": [], "push": []}
    real_reply, real_push = line_client.reply, line_client.push

    async def fake_reply(token, reply_token, messages):
        captured["reply"].append(messages)
        return True

    async def fake_push(token, to, messages):
        captured["push"].append(messages)
        return True

    line_client.reply = fake_reply
    line_client.push = fake_push
    yield captured
    line_client.reply = real_reply
    line_client.push = real_push


def test_line_webhook_follow_and_link(client, line_capture):
    admin_token = client.post(
        "/api/auth/login", json={"email": "admin@example.com", "password": "admin"}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {admin_token}"}

    # สร้าง channel (ต้องมีสิทธิ์ line_oa.manage — superuser ผ่าน)
    r = client.post(
        "/api/line/channels",
        json={
            "name": "test OA",
            "channel_id": "C0001",
            "channel_secret": "sec-1",
            "access_token": "tok-1",
            "greeting": "สวัสดีครับ ยินดีต้อนรับ",
            "quick_menu": [{"label": "เมนู", "url": "https://liff.line.me/xxx"}],
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text

    # ลายเซ็นผิด -> 400
    r = client.post(
        "/api/line/webhook/C0001",
        content=b"{}",
        headers={"x-line-signature": "bad", "content-type": "application/json"},
    )
    assert r.status_code == 400

    # follow -> ได้ greeting พร้อม quick reply
    r = _line_post(
        client,
        "C0001",
        "sec-1",
        {"events": [{"type": "follow", "replyToken": "rt1", "source": {"userId": "U111"}}]},
    )
    assert r.status_code == 200
    greeting = line_capture["reply"][-1][0]
    assert "ยินดีต้อนรับ" in greeting["text"]
    assert greeting["quickReply"]["items"][0]["action"]["label"] == "เมนู"

    # ขอ link code แล้วพิมพ์ link <code> ใน LINE -> ผูกบัญชีสำเร็จ
    code = client.post("/api/line/link-code", headers=headers).json()["code"]
    _line_post(
        client,
        "C0001",
        "sec-1",
        {
            "events": [
                {
                    "type": "message",
                    "replyToken": "rt2",
                    "source": {"userId": "U111"},
                    "message": {"type": "text", "text": f"link {code}"},
                }
            ]
        },
    )
    assert "สำเร็จ" in line_capture["reply"][-1][0]["text"]

    # โค้ดใช้ซ้ำไม่ได้
    _line_post(
        client,
        "C0001",
        "sec-1",
        {
            "events": [
                {
                    "type": "message",
                    "replyToken": "rt3",
                    "source": {"userId": "U111"},
                    "message": {"type": "text", "text": f"link {code}"},
                }
            ]
        },
    )
    assert "ไม่ถูกต้อง" in line_capture["reply"][-1][0]["text"]


def test_line_agent_bridge(client, line_capture, monkeypatch):
    from types import SimpleNamespace

    from addons.ai_agent.runtime import AgentRuntime

    monkeypatch.setattr(
        AgentRuntime,
        "_stream_ctx",
        lambda self, *, system, messages, tools: FakeStream(
            ["ตอบจาก agent ครับ"],
            SimpleNamespace(
                content=[{"type": "text", "text": "ตอบจาก agent ครับ"}],
                stop_reason="end_turn",
            ),
        ),
    )

    _line_post(
        client,
        "C0001",
        "sec-1",
        {
            "events": [
                {
                    "type": "message",
                    "replyToken": "rt4",
                    "source": {"userId": "U111"},
                    "message": {"type": "text", "text": "ระบบนี้คืออะไร"},
                }
            ]
        },
    )
    assert line_capture["reply"][-1][0]["text"] == "ตอบจาก agent ครับ"

    # U111 ผูกกับ admin แล้ว -> agent session ต้องเป็นของ admin (title ขึ้นต้น LINE:)
    admin_token = client.post(
        "/api/auth/login", json={"email": "admin@example.com", "password": "admin"}
    ).json()["access_token"]
    sessions = client.get(
        "/api/agent/sessions", headers={"Authorization": f"Bearer {admin_token}"}
    ).json()
    assert any(s["title"].startswith("LINE:") for s in sessions)


def test_faq_module(client):
    # หน้า HTML จาก templates ของโมดูล (kernel templating)
    r = client.get("/faq")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "คำถามที่พบบ่อย" in r.text
    assert "ระบบนี้คืออะไร" in r.text  # seed จาก on_install

    # API สาธารณะ
    faqs = client.get("/api/faq").json()
    assert len(faqs) >= 2

    # สร้างต้องมีสิทธิ์ faq.manage — user ธรรมดาโดน 403
    user_token = client.post(
        "/api/auth/login", json={"email": "somchai@example.com", "password": "pw1234"}
    ).json()["access_token"]
    r = client.post(
        "/api/faq",
        json={"question": "x", "answer": "y"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert r.status_code == 403

    # tool สาธารณะ: user ไม่มี role ก็เห็น search_faq (แต่ไม่เห็น count_users)
    tools = {
        t["name"]
        for t in client.get(
            "/api/agent/tools", headers={"Authorization": f"Bearer {user_token}"}
        ).json()
    }
    assert "search_faq" in tools
    assert "count_users" not in tools


def test_agent_chat_page(client):
    r = client.get("/agent")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "AI Agent" in r.text


def test_api_keys(client):
    token = client.post(
        "/api/auth/login", json={"email": "admin@example.com", "password": "admin"}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # สร้าง key — plaintext แสดงครั้งเดียว
    r = client.post("/api/keys", json={"name": "ci-bot"}, headers=headers)
    assert r.status_code == 201, r.text
    created = r.json()
    api_key = created["key"]
    assert api_key.startswith("psk_")

    # ใช้ API key แทน JWT ได้ทุก endpoint
    key_headers = {"Authorization": f"Bearer {api_key}"}
    r = client.get("/api/users/me", headers=key_headers)
    assert r.status_code == 200
    assert r.json()["email"] == "admin@example.com"

    # list ไม่มี plaintext — มีแค่ prefix
    listed = client.get("/api/keys", headers=headers).json()
    assert all("key" not in k for k in listed)
    assert any(k["key_prefix"] == api_key[:12] for k in listed)

    # revoke แล้วใช้ไม่ได้
    r = client.delete(f"/api/keys/{created['id']}", headers=headers)
    assert r.status_code == 204
    assert client.get("/api/users/me", headers=key_headers).status_code == 401

    # key มั่ว -> 401
    assert (
        client.get(
            "/api/users/me", headers={"Authorization": "Bearer psk_invalid"}
        ).status_code
        == 401
    )


def _rpc(client, headers, method, params=None, rpc_id=1):
    payload = {"jsonrpc": "2.0", "id": rpc_id, "method": method}
    if params is not None:
        payload["params"] = params
    return client.post("/mcp", json=payload, headers=headers)


def test_mcp_server(client):
    token = client.post(
        "/api/auth/login", json={"email": "admin@example.com", "password": "admin"}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    api_key = client.post(
        "/api/keys", json={"name": "mcp-client"}, headers=headers
    ).json()["key"]
    key_headers = {"Authorization": f"Bearer {api_key}"}

    # ไม่มี token -> 401, GET -> 405
    assert client.post("/mcp", json={}).status_code == 401
    assert client.get("/mcp", headers=key_headers).status_code == 405

    # initialize
    r = _rpc(client, key_headers, "initialize", {"protocolVersion": "2025-06-18"})
    result = r.json()["result"]
    assert result["serverInfo"]["name"] == "pstack"
    assert "tools" in result["capabilities"]

    # notification -> 202 ตัวเปล่า
    r = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers=key_headers,
    )
    assert r.status_code == 202

    # tools/list — superuser เห็น tools จากหลายโมดูล
    tools = {t["name"]: t for t in _rpc(client, key_headers, "tools/list").json()["result"]["tools"]}
    assert "count_users" in tools and "search_faq" in tools
    assert tools["search_faq"]["inputSchema"]["properties"]["query"]["type"] == "string"

    # tools/call — รัน tool จริงบน DB
    r = _rpc(client, key_headers, "tools/call", {"name": "count_users", "arguments": {}})
    result = r.json()["result"]
    assert result["isError"] is False
    assert "ผู้ใช้" in result["content"][0]["text"]

    # tool ที่ไม่มี/ไม่มีสิทธิ์ -> JSON-RPC error
    r = _rpc(client, key_headers, "tools/call", {"name": "nope", "arguments": {}})
    assert r.json()["error"]["code"] == -32602

    # user ไม่มี role เห็นเฉพาะ tool สาธารณะ
    user_token = client.post(
        "/api/auth/login", json={"email": "somchai@example.com", "password": "pw1234"}
    ).json()["access_token"]
    user_key = client.post(
        "/api/keys",
        json={"name": "user-bot"},
        headers={"Authorization": f"Bearer {user_token}"},
    ).json()["key"]
    tools = {
        t["name"]
        for t in _rpc(
            client, {"Authorization": f"Bearer {user_key}"}, "tools/list"
        ).json()["result"]["tools"]
    }
    assert "search_faq" in tools
    assert "count_users" not in tools


def test_external_addons_path(client):
    # โมดูลจาก tests/ext_addons ถูกโหลดคู่กับ addons/ หลัก (คนละ base dir)
    assert "extdemo" in client.get("/healthz").json()["modules"]
    assert client.get("/api/extdemo/ping").json()["status"] == "ok"


def test_duplicate_addons_basename_rejected(tmp_path):
    from core.loader import ModuleError, discover

    (tmp_path / "addons").mkdir()
    try:
        discover(["addons", str(tmp_path / "addons")])
        raise AssertionError("ต้อง raise ModuleError เมื่อชื่อ base dir ซ้ำ")
    except ModuleError as e:
        assert "ซ้ำ" in str(e)


def test_loader_table_detection_order_independent():
    """issue #1: ตรวจตารางต้องได้ครบแม้โมดูลถูก import ก่อน create_app()
    (รวม bare Table อย่าง user_roles ที่ไม่มี mapper) — regression lock"""
    import importlib

    import addons.users.models  # noqa: F401 — จำลอง pre-import (โมดูลอยู่ใน sys.modules แล้ว)
    from core.loader import _collect_table_names, discover

    info = discover(["addons"])["users"]
    models_mod = importlib.import_module("addons.users.models")
    tables = _collect_table_names(info, models_mod)
    # ORM models + association table ต้องมาครบ ไม่ว่าใครจะ import ก่อน
    assert {"users", "roles", "user_roles"} <= set(tables)


def test_periodic_job_registration():
    """issue #2: @periodic_job ต้องเข้า cron_jobs ของ worker"""
    from core import jobs

    before = len(jobs._periodic)

    @jobs.periodic_job(minute={0}, hour={9})
    async def _demo_tick(ctx):
        return None

    assert any(fn.__name__ == "_demo_tick" for fn, _ in jobs._periodic)
    ws = jobs.build_worker_settings()
    assert len(ws.cron_jobs) == len(jobs._periodic) == before + 1
    # background_job เดิมยังทำงานแยกกัน
    assert "_demo_tick" not in jobs._jobs
    jobs._periodic.pop()  # cleanup ไม่ให้ค้างข้ามเทส


def test_jobs_public_accessors():
    """issue #8: public accessor ของ background/periodic job (คู่กับ get_tools)"""
    from core import jobs

    @jobs.background_job
    async def _acc_bg(ctx):
        return None

    @jobs.periodic_job(minute={0})
    async def _acc_tick(ctx):
        return None

    assert "_acc_bg" in jobs.background_jobs()
    assert any(fn.__name__ == "_acc_tick" for fn, _ in jobs.periodic_jobs())
    # accessor คืน copy — แก้ผลลัพธ์ไม่กระทบ registry จริง
    jobs.background_jobs().clear()
    assert "_acc_bg" in jobs.background_jobs()
    del jobs._jobs["_acc_bg"]
    jobs._periodic[:] = [x for x in jobs._periodic if x[0].__name__ != "_acc_tick"]


def test_isolated_session_helper():
    """issue #8: helper สร้าง engine แยกต่อเทส (ไม่แตะ global engine)"""
    import asyncio

    from sqlalchemy import text

    from core.testing import isolated_session

    async def _run():
        async with isolated_session("sqlite+aiosqlite:///:memory:") as s:
            assert (await s.execute(text("SELECT 1"))).scalar_one() == 1

    asyncio.run(_run())


def test_revision_is_empty(tmp_path):
    """issue #7: ตรวจ revision เปล่า (ไม่มี op.)"""
    from core.migrations import revision_is_empty

    empty = tmp_path / "empty.py"
    empty.write_text("def upgrade():\n    pass\n")
    assert revision_is_empty(empty) is True

    full = tmp_path / "full.py"
    full.write_text("def upgrade():\n    op.create_table('x')\n")
    assert revision_is_empty(full) is False


def test_event_bus_local():
    import asyncio

    from core.events import EventBus

    bus = EventBus()
    received = []

    @bus.on("test.event")
    async def handler(payload):
        received.append(payload)

    asyncio.run(bus.emit("test.event", {"x": 1}))
    assert received == [{"x": 1}]


def test_tool_registry():
    from core.ai import get_tools

    tools = {t.name: t for t in get_tools()}
    assert "count_users" in tools
    assert "search_users" in tools
    schema = tools["search_users"].input_schema
    assert schema["properties"]["query"]["type"] == "string"
    assert "query" in schema["required"]
