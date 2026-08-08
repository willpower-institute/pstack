# Changelog

App repos (pstack-vdo, pstack-lms, ...) ควร pin `PSTACK_REF` เป็น tag ในนี้เสมอ
และอัปเกรดเป็นรอบๆ — breaking change จะถูกจดไว้ที่นี่ทุกครั้ง

## Compatibility

| App repo | pstack tag |
|---|---|
| pstack-vdo | v0.1.0 |

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
