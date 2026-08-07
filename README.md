# pstack

Modular BaaS / Dev Framework บน FastAPI — ขยายได้ด้วยระบบโมดูลสไตล์ Odoo พร้อมโมดูล AI Agent ในตัว

## แนวคิด

- **Kernel เล็ก + ทุกอย่างเป็นโมดูล** — module loader อ่าน `__manifest__.py`, จัดลำดับตาม `depends`, มี lifecycle install/upgrade/uninstall
- **โมดูลลงทะเบียน extension points ได้** — routers, models, **templates/static (server-rendered UI)**, event handlers, permissions, background jobs และ **AI tools**
- **AI Agent เป็น first-class** — โมดูลไหนก็ expose tool ให้ agent เรียกใช้ได้ ภายใต้ RBAC ของ user
- **รองรับการย้ายโปรเจกต์เดิม** — โปรเจกต์ FastAPI เดี่ยวๆ ย้ายมาเป็น addon หนึ่งตัวได้ ดู [docs/MIGRATION.md](docs/MIGRATION.md)

## Tech Stack

| ส่วน | ใช้ |
|---|---|
| Web | FastAPI + Pydantic v2 |
| ORM | SQLAlchemy 2.0 (async) + Alembic |
| Database | PostgreSQL |
| Cache / Event | Redis |
| Background jobs | ARQ |
| AI | Anthropic SDK (Claude) |

## โครงสร้าง

```
├── core/          # kernel: loader, registry, db, auth, events, jobs, ai
├── addons/        # โมดูลทั้งหมด (users, storage, ai_agent, line_oa, ...)
├── cli.py         # pstack CLI
└── docker-compose.yml
```

## โมดูลที่วางแผนไว้

| โมดูล | หน้าที่ |
|---|---|
| `users` | auth (JWT), RBAC, user management |
| `storage` | file upload / object storage |
| `ai_agent` | tool registry, agent runtime (Claude), SSE chat API |
| `line_oa` | LINE Official Account — webhook (verify signature), หลาย channel, **LIFF**, account linking, quick-reply menu เป็น data, push/flex message และ bridge เข้า AI agent (แชทบอท AI บน LINE ภายใต้สิทธิ์ของ user ที่ผูกไว้) |

## Roadmap

- [x] Phase 0 — Scaffold (โครงโปรเจกต์, docker-compose)
- [x] Phase 1 — Kernel (module loader, manifest, registry, CLI) — *Alembic per-module migration ยังเป็น create-table-on-install จะเสริมใน Phase 2*
- [ ] Phase 2 — Core modules (users/auth/RBAC, storage, event bus)
- [ ] Phase 3 — AI Agent module (tool registry, agent runtime, SSE chat API)
- [ ] Phase 4 — DX + Channel modules (`line_oa`, module generator, docs, ตัวอย่างโมดูล)
- [ ] Phase 5 — Multi-tenant, admin UI

## Development

```bash
# แบบ Docker (app + postgres + redis)
cp .env.example .env
docker compose up -d --build
curl http://localhost:8000/healthz

# แบบ local venv
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python cli.py run            # dev server (ต้องมี postgres)
.venv/bin/python -m pytest tests/     # smoke tests (รันบน sqlite ไม่ต้องมี DB)

# CLI
python cli.py modules                  # ดูโมดูลทั้งหมด + สถานะติดตั้ง
python cli.py new-module <name>        # สร้างโครง addon ใหม่
```

Login แรก: `admin@example.com` / `admin` (ตั้งค่าผ่าน `PSTACK_ADMIN_EMAIL`/`PSTACK_ADMIN_PASSWORD` — เปลี่ยนใน production)

## การเขียนโมดูล

```
addons/<name>/
├── __manifest__.py   # dict literal: name, version, depends
├── models.py         # SQLAlchemy models (สร้างตารางอัตโนมัติตอน install)
├── routes.py         # ต้องมีตัวแปร router: APIRouter
├── services.py       # business logic
├── tools.py          # @agent_tool — expose ให้ AI agent
├── hooks.py          # on_install(session) / on_upgrade(session, from_version)
├── templates/        # Jinja2 อ้างแบบ "<name>/page.html"
└── static/           # mount ที่ /static/<name>/
```

เปิดใช้โมดูลโดยเพิ่มชื่อเข้า `PSTACK_MODULES` ใน `.env` — kernel resolve dependency, สร้างตาราง, รัน hook ให้อัตโนมัติตอนบูต ดูตัวอย่างเต็มที่ `addons/users/`
