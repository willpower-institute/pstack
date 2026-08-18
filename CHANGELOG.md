# Changelog

App repos (pstack-vdo, pstack-lms, ...) ควร pin `PSTACK_REF` เป็น tag ในนี้เสมอ
และอัปเกรดเป็นรอบๆ — breaking change จะถูกจดไว้ที่นี่ทุกครั้ง

## Compatibility

| App repo | pstack tag |
|---|---|
| pstack-vdo | v0.1.0 |
| care-agent-platform | v0.1.1 |

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
