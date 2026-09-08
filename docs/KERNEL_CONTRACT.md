# Kernel Public Contract

kernel เปิด symbol ชุดหนึ่งให้ **consumer app** (care, vdo, vituntasa, pstack-app-template)
และ **addon** พึ่งพา ชุดนี้คือ "สัญญา" ที่ consumer สร้างบนสมมติฐานว่ามันจะไม่เปลี่ยนเงียบ ๆ

ปัญหาที่ contract นี้แก้: kernel dev แก้ signature หรือลบ symbol แล้ว test ของ kernel ยังเขียว
แต่ consumer พังตอน `pip install` เวอร์ชันใหม่ — เป็นความล้มเหลวที่โผล่ปลายทาง ไกลจากจุดที่แก้

## กลไก

- `contract/kernel-contract.json` — **snapshot** ของ public surface ที่ commit ไว้ (รูปร่าง ไม่ใช่ค่า)
- `tests/test_kernel_contract.py` — introspect surface จริงของ kernel แล้วเทียบกับ snapshot
  - ต่างกัน → เทสแดงพร้อม diff ว่า symbol/param ไหนหาย เปลี่ยน หรือเพิ่ม
  - เทสนี้อยู่ใน `pytest tests/` อยู่แล้ว → เป็นส่วนของ required check `ci` โดยไม่ต้องแก้ workflow

`SURFACE` ในไฟล์เทสคือรายชื่อ symbol สาธารณะ (ได้มาจาก grep การ import จริงใน `addons/`)
snapshot เก็บ **ชื่อ param ตามลำดับ** เท่านั้น ไม่เก็บ type annotation → เสถียรข้าม Python version
และจับสิ่งที่ทำ consumer พังจริง: ลบ param, เปลี่ยนชื่อ param, ทำ param ให้บังคับ, ลบ/เปลี่ยนชื่อ symbol

รูปแบบ param ใน snapshot:

| เขียน | หมายถึง |
|---|---|
| `name` | param บังคับ |
| `name?` | param ที่มี default (optional) |
| `*name` / `**name` | `*args` / `**kwargs` |

## เปลี่ยน contract อย่างไร

การเปลี่ยน surface โดยตั้งใจ (เพิ่ม/ลบ symbol, แก้ signature) ให้ re-sync snapshot:

```bash
PSTACK_UPDATE_CONTRACT=1 pytest tests/test_kernel_contract.py
```

แล้ว **review diff ของ `contract/kernel-contract.json`** ใน PR — diff นี้คือหลักฐานว่าเปลี่ยนอะไร
ต่อ consumer และต้อง:

1. บันทึกใน `CHANGELOG.md` — ถ้าลบ/เปลี่ยน signature ที่ consumer ใช้อยู่ = **breaking** ต้องขึ้นเวอร์ชันตาม semver
2. อัปเดต compatibility table ถ้ากระทบ pin ของ consumer
3. ถ้าเพิ่ม symbol สาธารณะใหม่ ต้องเพิ่มชื่อใน `SURFACE` ก่อน (ไม่งั้น snapshot จะไม่ครอบ)

## ขอบเขต — contract นี้ล็อกอะไร / ไม่ล็อกอะไร

ล็อก **รูปร่าง** ของ surface: มี symbol ไหน เป็น function/class/constant ชื่อ param อะไร

**ไม่** ล็อก **ค่า** หรือ **พฤติกรรม** — เช่น regex จริงของ `core.tenancy.ID_PATTERN` ที่ต้องตรงกับ
`identity/v1 $defs.Id` ข้าม repo ยังเป็นหน้าที่ของเทสเฉพาะทาง
`tests/test_tenancy.py::test_id_pattern_is_identity_v1_contract` — contract นี้เสริม ไม่ทดแทน

หลักการเดียวกับที่ทีมตกลงบน ai-collab: ข้อกล่าวอ้างที่ "ผิดแล้ว CI consumer แดง" ต้องอยู่ใน git
พร้อม conformance test — kernel contract คือการทำหลักนั้นให้ครอบทั้ง public surface ไม่ใช่แค่ตัวเดียว
