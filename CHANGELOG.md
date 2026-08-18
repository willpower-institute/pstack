# Changelog

App repos (pstack-vdo, pstack-lms, ...) ควร pin `PSTACK_REF` เป็น tag ในนี้เสมอ
และอัปเกรดเป็นรอบๆ — breaking change จะถูกจดไว้ที่นี่ทุกครั้ง

## Compatibility

| App repo | pstack tag |
|---|---|
| pstack-vdo | v0.1.0 |
| care-agent-platform | v0.1.1 |

## Unreleased

- **แก้บั๊ก worker (#4):** service `worker` ใน `docker-compose.yml` บูตไม่ขึ้นเลยตั้งแต่ v0.1.0
  — `arq` เป็น console script จึงไม่มี CWD ใน `sys.path` ทำให้ import `core`/`addons` จาก
  site-packages (ซึ่งติดตั้ง `addons` ไว้แค่ `__init__.py`) แล้วพังด้วย
  `ModuleNotFoundError: No module named 'addons.users'` · เปลี่ยนเป็น `python -m arq`
  ซึ่งใส่ CWD ให้เหมือนที่ uvicorn ทำกับ service `app`
  **ผลกระทบ:** background job และ periodic job (v0.2.0) ไม่เคยทำงานจริงในการ deploy ด้วย compose

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
