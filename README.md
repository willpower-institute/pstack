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
| `ai_agent` | agent runtime (Claude `claude-opus-5` + refusal fallbacks), chat session ต่อ user, SSE streaming, เรียก tools ของโมดูลอื่นภายใต้สิทธิ์ RBAC ของผู้ใช้ |
| `line_oa` | LINE Official Account — webhook (verify signature), หลาย channel, **LIFF**, account linking, quick-reply menu เป็น data, push/flex message และ bridge เข้า AI agent (แชทบอท AI บน LINE ภายใต้สิทธิ์ของ user ที่ผูกไว้) |
| `faq` | **โมดูลตัวอย่าง** — หน้า HTML จาก templates ของโมดูล (`/faq`), REST API, AI tool สาธารณะ (`search_faq` — guest บน LINE ถามได้), seed data |
| `api_keys` | long-lived API key (`psk_...`) สำหรับ machine/agent ภายนอก — hash เก็บ, revoke ได้, ใช้แทน JWT ได้ทุก endpoint |
| `mcp_server` | เปิด tool registry ทั้งหมดให้ AI ภายนอกผ่าน **MCP** (`POST /mcp`, Streamable HTTP) — tools กรองตาม RBAC ของเจ้าของ token |

## Roadmap

- [x] Phase 0 — Scaffold (โครงโปรเจกต์, docker-compose)
- [x] Phase 1 — Kernel (module loader, manifest, registry, CLI)
- [x] Phase 2 — Alembic per-module migrations, `storage`, Redis event bus, ARQ background jobs
- [x] Phase 3 — AI Agent module (agent runtime บน Claude, SSE chat API, RBAC-scoped tools)
- [x] Phase 4 — `line_oa` (webhook หลาย channel, account linking, agent bridge), module generator
- [x] Phase 4.5 — DX: โมดูลตัวอย่าง `faq`, หน้าแชท `/agent`, [MODULE_GUIDE](docs/MODULE_GUIDE.md), CI
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
python cli.py makemigration <module> -m "..."   # สร้าง alembic revision ของโมดูล
python cli.py migrate                  # apply migrations + install/upgrade ทุกโมดูล
```

Login แรก: `admin@example.com` / `admin` (ตั้งค่าผ่าน `PSTACK_ADMIN_EMAIL`/`PSTACK_ADMIN_PASSWORD` — เปลี่ยนใน production)

## การเขียนโมดูล

```
addons/<name>/
├── __manifest__.py   # dict literal: name, version, depends
├── models.py         # SQLAlchemy models
├── routes.py         # ต้องมีตัวแปร router: APIRouter
├── services.py       # business logic
├── tools.py          # @agent_tool — expose ให้ AI agent
├── jobs.py           # @background_job — งานเบื้องหลังผ่าน ARQ worker
├── hooks.py          # on_install(session) / on_upgrade(session, from_version)
├── migrations/       # alembic ต่อโมดูล (สร้างด้วย cli makemigration; ไม่มีก็ create-table ให้)
├── templates/        # Jinja2 อ้างแบบ "<name>/page.html"
└── static/           # mount ที่ /static/<name>/
```

**Schema เปลี่ยน?** แก้ models.py แล้ว `python cli.py makemigration <module> -m "คำอธิบาย"` — แต่ละโมดูลมี lineage และ version table ของตัวเอง (`alembic_version_<module>`) ไม่ชนกัน

**Event ข้ามโมดูล/ข้ามโปรเซส:** `ctx.events.on("users.created")` / `await ctx.events.emit(..., broadcast=True)` (broadcast ผ่าน Redis ไปถึง worker ด้วย)

## ใช้งาน AI Agent

ตั้ง `ANTHROPIC_API_KEY` ใน `.env` แล้ว:

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/auth/login \
  -H 'content-type: application/json' \
  -d '{"email":"admin@example.com","password":"admin"}' | jq -r .access_token)

SID=$(curl -s -X POST localhost:8000/api/agent/sessions \
  -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{}' | jq -r .id)

# แชท (ตอบเป็น SSE stream) — agent เรียก tools ได้เฉพาะที่ user มีสิทธิ์
curl -N -X POST localhost:8000/api/agent/sessions/$SID/messages \
  -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"text":"ตอนนี้มีผู้ใช้กี่คน"}'

curl -s localhost:8000/api/agent/tools -H "authorization: Bearer $TOKEN"   # tools ที่ agent ใช้ได้
```

การเขียน tool ให้ agent — วางใน `addons/<module>/tools.py`:

```python
from core.ai import agent_tool

@agent_tool(module="crm", permission="crm.read")
async def search_customers(session, query: str) -> str:
    """ค้นหาลูกค้าจากชื่อหรืออีเมล"""   # docstring = คำอธิบายที่ agent เห็น
    ...
```

## ใช้งาน LINE OA

1. สร้าง channel ในระบบ (ใช้ค่าจาก LINE Developers Console):

```bash
curl -X POST localhost:8000/api/line/channels \
  -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"name":"OA ของเรา","channel_id":"<LINE channel ID>",
       "channel_secret":"<secret>","access_token":"<long-lived token>",
       "greeting":"สวัสดีครับ","quick_menu":[{"label":"เมนู","url":"https://liff.line.me/xxx"}]}'
```

2. ตั้ง webhook URL ใน LINE Console: `https://<โดเมน>/api/line/webhook/<LINE channel ID>`
3. เท่านี้แชทที่ทักเข้า OA จะถูกส่งเข้า AI agent อัตโนมัติ (ปิดได้ด้วย `agent_enabled: false` — โมดูลอื่น subscribe event `line.message.received` ไปตอบเองได้)

**ผูกบัญชี:** user เรียก `POST /api/line/link-code` ได้โค้ด แล้วพิมพ์ `link <โค้ด>` ในแชท LINE — จากนั้น agent จะทำงานภายใต้สิทธิ์ RBAC ของ user คนนั้น (ยังไม่ผูก = guest ใช้ได้เฉพาะ tools สาธารณะ)

**Broadcast:** `await enqueue("line_broadcast", channel_pk, "ข้อความ")` — ส่งผ่าน ARQ worker

## ให้ AI ภายนอกต่อเข้าระบบ (MCP)

1. สร้าง API key: `POST /api/keys {"name":"my-agent"}` — ได้ `psk_...` (แสดงครั้งเดียว, revoke ได้ที่ `DELETE /api/keys/{id}`)
2. ต่อจาก Claude Code:

```bash
claude mcp add pstack --transport http https://<โดเมน>/mcp \
  --header "Authorization: Bearer psk_xxx"
```

AI ภายนอกจะเห็น **tools ชุดเดียวกับ agent ภายใน** กรองตามสิทธิ์ RBAC ของ user เจ้าของ key — โมดูลใหม่เพิ่ม `@agent_tool` ปุ๊บ MCP client เห็นทันที ไม่ต้องแก้อะไร

(อีกทางที่ใช้ได้เลย: agent ภายนอกคุยกับ agent ของเราเป็นภาษาคนผ่าน `POST /api/agent/sessions/{id}/messages` โดย auth ด้วย API key เดียวกัน)

เปิดใช้โมดูลโดยเพิ่มชื่อเข้า `PSTACK_MODULES` ใน `.env` — kernel resolve dependency, สร้างตาราง, รัน hook ให้อัตโนมัติตอนบูต

📖 **คู่มือเต็ม: [docs/MODULE_GUIDE.md](docs/MODULE_GUIDE.md)** — เดินทีละขั้นพร้อมชี้ตัวอย่างจริง (โมดูล `faq` ตั้งใจเขียนไว้เป็นตัวอย่างครบทุก pattern)

## สร้าง app แยก repo บนฐาน pstack

app repo (เช่น `pstack-vdo`, `pstack-lms`) เก็บเฉพาะ addons ของตัวเอง แล้ว **pin pstack เป็น tag**
— เริ่มจาก template repo [`pstack-app-template`](https://github.com/willpower-institute/pstack-app-template) (กด "Use this template")

```bash
PSTACK_ADDONS_PATHS=addons,vdo_addons     # ชื่อ base dir ต้องไม่ซ้ำกัน
PSTACK_MODULES=users,storage,vdo
```

กติกา: app ไม่แตะโค้ด pstack — อยากได้อะไรจาก kernel ให้ทำฝั่งนี้แล้วออก tag ใหม่
ดู breaking changes + ตาราง compatibility ใน [CHANGELOG.md](CHANGELOG.md)

**ลองเล่นเร็วสุด:** `docker compose up -d --build` แล้วเปิด `http://localhost:8000/agent` (หน้าแชทกับ AI) และ `http://localhost:8000/faq` (หน้า HTML จากโมดูลตัวอย่าง)

## License

MIT — ดู [LICENSE](LICENSE)
