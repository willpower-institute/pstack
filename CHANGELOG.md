# Changelog

App repos (pstack-vdo, pstack-lms, ...) ควร pin `PSTACK_REF` เป็น tag ในนี้เสมอ
และอัปเกรดเป็นรอบๆ — breaking change จะถูกจดไว้ที่นี่ทุกครั้ง

## Compatibility

| App repo | pstack tag |
|---|---|
| pstack-vdo | v0.1.0 |
| care-agent-platform | v0.1.1 |

## v0.2.1 — 2026-08-18

จาก feedback care-agent-platform (issues #4, #7, #8) — **ไม่มี breaking change**

- **แก้บั๊ก worker บูตไม่ขึ้น (#4):** `command: arq core.worker.WorkerSettings` ใน compose เป็น
  console script → Python ไม่ใส่ CWD ลง `sys.path` → resolve `core`/`addons` จาก site-packages
  (ที่ไม่มี addons ย่อย) → `ModuleNotFoundError` **background/periodic job ไม่เคยทำงานใน docker
  ตั้งแต่ v0.1.0** · แก้เป็น `python -m arq core.worker.WorkerSettings` (ทั้ง pstack และ template)
- **makemigration ปฏิเสธ revision เปล่า (#7):** revision แรกที่ออกมาว่าง (ไม่มี `op.`) มักแปลว่า
  ตารางถูกสร้างด้วย create-table fallback ไปก่อน — ตอนนี้ลบไฟล์เปล่าให้ + บอกวิธีแก้ + exit 1
  (เดิมเงียบ แล้วไปพังตอน deploy เครื่องใหม่)
- **DX (#8):** `core.jobs.periodic_jobs()` / `background_jobs()` public accessor (คู่กับ `get_tools`) ·
  `core.testing.isolated_session` helper เลี่ยงบั๊ก global engine ผูก event loop บนเทส async (Postgres)

## v0.2.0 — 2026-08-18

จาก feedback ของ consumer จริง (care-agent-platform issues #1, #2) — **ไม่มี breaking change**

- **แก้บั๊ก loader (#1):** โมดูลที่ถูก import เข้า `sys.modules` ก่อน `create_app()` เคยไม่ถูก
  สร้างตารางให้ (diff `Base.metadata` ได้เซตว่าง) แล้วล้มเงียบ `no such table` ตอน query —
  เปลี่ยนมาหาตารางจาก namespace ของ `models.py` โดยตรง ได้ผลเท่ากันทุกลำดับการ import และ
  จับ bare `Table()` (association table เช่น `user_roles`) ได้ด้วย · เลิกใช้ `_module_tables_cache`
- **Periodic/cron jobs (#2):** เพิ่ม `@periodic_job(**cron_kwargs)` ให้โมดูลลงทะเบียน job ที่
  worker เดินเองเป็นระยะ (ที่เดิมทำได้แค่ `@background_job` แบบสั่งแล้วรัน) — `build_worker_settings()`
  ประกอบ `cron_jobs` ให้อัตโนมัติ · cron ยึดเวลา UTC ของ container
- app repo ที่ต้องการ periodic job หรือมีเทสที่ import addon ที่ระดับ top-level → อัปเป็น v0.2.0

## v0.1.1 — 2026-08-18

**ใส่สัญญาอนุญาต** — ไม่มีการเปลี่ยนโค้ด อัปเกรดจาก v0.1.0 ได้ทันทีโดยไม่ต้องแก้อะไร

- เพิ่มไฟล์ `LICENSE` (MIT) — ก่อนหน้านี้ repo ไม่มีสัญญาอนุญาต ซึ่งตามกฎหมายลิขสิทธิ์
  หมายถึง all rights reserved ทำให้ app repo ที่เป็น open source ใช้ pstack เป็นฐานไม่ได้
- `pyproject.toml`: เพิ่ม `license` และ `readme`

## v0.1.0 — 2026-08-09

รีลีสแรกสำหรับให้ app repo ภายนอก pin ใช้

- **Kernel:** module loader (manifest + dependency resolution + external addons paths),
  install/upgrade registry, per-module Alembic migrations, async SQLAlchemy,
  JWT auth + RBAC + token resolvers (API key), event bus (in-process + Redis broadcast),
  ARQ background jobs, namespaced Jinja2 templating, AI tool registry, typer CLI
- **Modules:** `users`, `storage`, `ai_agent` (Claude runtime + SSE chat + `/agent` UI),
  `line_oa` (multi-channel + agent bridge), `faq` (ตัวอย่าง), `api_keys`, `mcp_server`
- **External addons:** ตั้ง `PSTACK_ADDONS_PATHS=addons,<app>_addons` ได้ —
  base dir ชื่อต้องไม่ซ้ำกัน, parent ถูกเพิ่มเข้า sys.path อัตโนมัติ
