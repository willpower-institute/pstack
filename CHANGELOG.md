# Changelog

App repos (pstack-vdo, pstack-lms, ...) ควร pin `PSTACK_REF` เป็น tag ในนี้เสมอ
และอัปเกรดเป็นรอบๆ — breaking change จะถูกจดไว้ที่นี่ทุกครั้ง

## Compatibility

| App repo | pstack tag |
|---|---|
| pstack-vdo | v0.1.0 |
| care-agent-platform | v0.3.1 |

## v0.4.0 — 2026-08-20

Security hardening review ทั้ง framework + ปิด follow-up ของ v0.3.2 (8 PR: #19–#26)

> ⚠️ **BREAKING (operator) — ต้องทำก่อน/หลัง upgrade:**
> 1. **ต้องตั้ง `PSTACK_SECRET_KEY`** เป็นค่าสุ่มยาว ≥32 ตัว ไม่งั้น **ระบบไม่บูต** (#22) —
>    `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'`
> 2. **`/docs` `/redoc` `/openapi.json` ปิดเมื่อ `PSTACK_DEBUG=false`** (#26) — ตั้ง
>    `PSTACK_EXPOSE_DOCS=true` ถ้ายังต้องการ
> 3. ถ้าใช้ RLS + `deploy/db-role.sql`: role ต้อง **เป็นเจ้าของตาราง** (owner) ไม่งั้น
>    migration ตอนบูตพัง (#20) — สคริปต์อัปเดตให้แล้ว
> 4. **รันหลัง reverse proxy? ต้องตั้ง `FORWARDED_ALLOW_IPS`** เป็น IP ของ proxy —
>    ไม่งั้น rate limit ต่อ IP จาก #24 จะกลายเป็นลิมิตรวมของทั้งระบบ
>    (ผู้ใช้จริงคนที่ 21 ในหนึ่งนาทีโดน 429) · ระบบจะ log warning ให้เมื่อตรวจพบ

**🔒 Security review (5 PR):**
- **#22 (critical):** `PSTACK_SECRET_KEY` default `"change-me"` (อยู่บน GitHub) → ปลอม JWT เป็น
  admin ได้โดยไม่ต้องรู้รหัส · ตอนนี้ปฏิเสธการบูตถ้าคีย์อ่อน/สั้นกว่า 32 (debug=true รันได้พร้อม warning)
- **#23 (high):** upload อ่านทั้งไฟล์เข้า RAM ก่อนเช็คขนาด → OOM DoS · เช็ค `upload.size` ก่อน +
  สตรีมทีละ 1MB (600MB: RSS 713MB → 94MB) · size ที่บันทึกมาจากไบต์จริง
- **#24 (high):** `/api/auth/login` ไม่มี rate limit → เดารหัสไม่จำกัด + bcrypt CPU DoS ·
  เพิ่ม `core/ratelimit.py` (Redis fixed-window, fallback in-process) — ต่อ IP 20/นาที +
  ต่อบัญชี 5/5นาที (นับเฉพาะครั้งล้มเหลว) · 429 + Retry-After · ตั้ง 0 = ปิด
- **#25 (medium):** timing attack — ไม่เจอ user ตอบ 6ms/เจอ 327ms → กวาดอีเมลได้ ·
  hash dummy (lru_cache) ให้เวลาเท่ากัน
- **#26 (medium):** `/docs` เปิดสาธารณะเสมอ → ผูกกับ `expose_docs` · เพิ่ม security header
  (`X-Content-Type-Options`/`X-Frame-Options`/`Referrer-Policy`) · SSE ไม่ส่ง exception ดิบออก client

**🔧 Follow-ups (ปิดของค้างจาก v0.3.2):**
- **#19:** ผูก tenant กับ **agent session ตอนสร้าง** (ปิดช่องข้าม tenant ของ agent ภายใน/LINE ที่ #16
  แก้แค่ฝั่ง MCP) — bind ครั้งเดียวตอนสร้าง (ไม่ใช่ต่อ turn เพราะแชทมีประวัติ) + ตรวจ membership ซ้ำ
  ทุก turn · `agent_sessions.tenant_id` nullable (session เดิม = NULL = พฤติกรรมเดิม) · รวม
  `authorize_tenant()` ให้ mcp ใช้ร่วม · **`ai_agent` → v1.1.0** (มี migration)
- **#20:** `deploy/db-role.sql` ต้องให้ role เป็น owner ตาราง (owner≠superuser · FORCE RLS ยังกรอง owner)
- **#21:** template migration (`_SCRIPT_MAKO`) สร้างไฟล์ที่ ruff I001 ไม่ผ่าน → CI แดงทุกครั้งที่เพิ่ม
  migration · แก้ที่ต้นทาง + สำเนาใน 7 โมดูล

## v0.3.2 — 2026-08-20

จาก consumer จริง (5 PR ของทีม care/workshop) — **ไม่มี breaking change** (#16 เพิ่ม API แบบ additive)

- **🔒 MCP ส่ง tenant context ถึง AI tool (#16):** เดิม `tool.fn(db, ...)` ส่ง session เปล่าให้ tool —
  RBAC คุมได้แค่ "เรียก tool ได้ไหม" ไม่คุม "เห็นข้อมูล tenant ไหน" → agent **ข้าม tenant ได้ผ่าน MCP**
  ทั้งที่ REST บล็อกแล้ว · แก้: `/mcp` รับ `X-Tenant-Id` → ตรวจ membership → `bind_tenant()` ให้ session
  ก่อนเรียก tool · เพิ่ม `core.tenancy.bound_tenant(session)` ให้ tool อ่าน tenant ที่ชั้นบนผูกไว้ ·
  **กติกา: tool ห้ามรับ `tenant_id` เป็นพารามิเตอร์** (เท่ากับยกให้ agent เลือก tenant เอง)
  - ⚠️ ยังเหลือ `ai_agent/runtime.py` (agent ภายใน/LINE bridge) ที่มีช่องเดียวกัน — รอออกแบบว่า
    agent session ผูก tenant ตอนไหน
- **🐛 worker ไม่เคย subscribe Redis (#14):** `connect_redis()` ถูกเรียกใน FastAPI lifespan เท่านั้น
  แต่ ARQ worker ไม่รัน lifespan → handler `@ctx.events.on` ในโปรเซส worker **ไม่เคยรับ event
  `broadcast=True` เลย** (เงียบ ไม่มี error ทั้งที่ README โฆษณาไว้) · แก้ผ่าน arq `on_startup`/`on_shutdown`
  hook · ⚠️ ห้าม subclass WorkerSettings (arq อ่าน `settings_cls.__dict__` ตรง ๆ — attribute ที่สืบทอดหาย)
- **🐛 line_oa signature non-ASCII → 500 (#13):** `hmac.compare_digest()` raise TypeError กับ `str`
  ที่มีอักขระ non-ASCII → webhook (public endpoint) ตอบ 500 แทน 400 · แก้: เทียบเป็น bytes (ยัง constant-time)
- **📄 default footgun: compose ให้ app ต่อ DB ด้วย superuser (#17):** `POSTGRES_USER=${DB_USER}` เป็น
  bootstrap superuser → RLS ทั้งหมดไร้ผล (superuser bypass) แม้ทำตาม §9 ครบ · เพิ่ม `deploy/db-role.sql`
  (สร้าง role ธรรมดา + ALTER DEFAULT PRIVILEGES) + `deploy/verify-rls.sh` (ตรวจ 5 ขั้น) + คำเตือนใน
  compose/.env.example/MODULE_GUIDE — ไม่แตะพฤติกรรมโค้ด
- **🧹 เทส hermetic (#15):** ย้าย env ของชุดเทสไป `tests/conftest.py` — เดิม `test_smoke.py` อ่าน `.env`
  ของเครื่อง dev (เปลี่ยนรหัส admin ตาม README แล้วเทสแดง) + `lru_cache` settings ทำให้บูต app ได้แค่
  ไฟล์เทสเดียว · ตอนนี้แยกไฟล์เทสต่อโมดูลได้แล้ว (แก้ `PSTACK_MODULES` ที่ conftest ที่เดียว)

## v0.3.1 — 2026-08-19

จาก care (issue #10 / care#4) — **ไม่มี breaking change** (`set_tenant()` ยังอยู่ · เพิ่ม API ใหม่)

- **`core.tenancy.bind_tenant()` / `unbind_tenant()`** — ผูก tenant กับ **session** แล้วตั้ง GUC
  ใหม่อัตโนมัติทุก transaction (ผ่าน event `after_begin`) จึง **รอดการ commit กลางทาง** ·
  `set_tenant()` เดิมตั้ง GUC แค่ transaction เดียว (หายเมื่อ commit) → โค้ดที่ commit แล้วอ่านต่อ
  หรือ background job ที่วนหลาย tenant เห็น 0 แถวแบบเงียบ ๆ (RLS deny-by-default) · care เจอตอน
  เปิด RLS: เทส 42 ตัวกลายเป็น "ไม่พบผู้ป่วย"
  - เก็บ binding บน `session.info` (**ไม่ใช่ `id(session)`** — id ถูกใช้ซ้ำหลัง GC ทำให้ session
    ใหม่รับ binding ของ session ที่ตายแล้ว · gotcha ที่ care เจอตอนเขียน workaround)
  - `get_scope` เปลี่ยนมาใช้ `bind_tenant()` → RLS ของตารางโดเมนกรองถูกแม้ service layer commit กลาง request
- **MODULE_GUIDE §9:** เพิ่มวิธีใช้ `bind_tenant` + คำเตือน footgun ของ `set_tenant` + pattern ให้
  background job discover tenant จากตาราง `tenant` (control plane ไม่มี RLS) ไม่ใช่ตารางโดเมนที่มี RLS

## v0.3.0 — 2026-08-19

Phase 5 (multi-tenant) — จาก design ร่วมกับ care-agent-platform (issue #3) · **ไม่มี breaking
change** สำหรับ app เดิม (โมดูล/ตารางใหม่ล้วน ๆ) — app ที่จะใช้ multi-tenant ค่อยเปิด `tenancy`

- **`core.tenancy` — primitives ที่ kernel เป็นเจ้าของ:** `ID_PATTERN` (ตรง identity/v1 `$defs.Id`
  — มี contract-lock test), `validate_id`/`new_id`, `Principal`, `TenantScope`, `scoped()`,
  `assert_same_tenant()`, `rls_statements()`, `set_tenant()` · โมดูลโดเมน import จากที่นี่
  (path-independent) ไม่ต้องรู้จัก addon
- **โมดูล `tenancy` (control plane):** ตาราง `tenant`/`workspace`/`tenant_member` (ชื่อกลาง ไม่มี
  prefix) + services + `get_scope` dependency (header `X-Tenant-Id`, non-member ตอบ 404 ไม่ใช่ 403)
  + REST จัดการ tenant/member/workspace
- **RLS เป็นด่าน DB กันพลาด:** `rls_statements(table)` เปิด `ENABLE`+**`FORCE ROW LEVEL SECURITY`**+
  policy กรองตาม GUC `pstack.tenant_id` (idempotent) · deny-by-default เมื่อไม่ตั้ง scope ·
  conformance test พิสูจน์ isolation จริงบน Postgres (owner+FORCE) — ⚠️ app **ห้าม**ต่อ DB ด้วย superuser
- **`core.clock`:** `now`/`set_now`/`FakeClock` (UTC-aware, ปฏิเสธ naive) — testable clock ระดับ kernel
- **`stamp` (adopt/rollback):** `migrations.stamp()` + `cli.py stamp <module> [--rev head]` — บันทึก
  version โดยไม่รัน migration
- **adopt ตารางเดิมได้แบบ idempotent:** initial migration ของ `tenancy` เจอตารางชื่อกลางอยู่แล้ว
  จะข้าม create + ให้ alembic บันทึกเอง (ไม่ต้อง stamp มือ, kernel ไม่รู้จัก prefix ของ consumer) +
  guard เตือนเมื่อ adopt ไม่ครบ · runbook + ตารางชื่อ canonical (constraint/index) ใน MODULE_GUIDE §9

## v0.2.2 — 2026-08-18

จาก feedback care-agent-platform (issue #6) — **ไม่มี breaking change**

- **line_oa `respond()` helper (#6):** โมดูลที่ subscribe `line.message.received` ไปตอบเอง
  เดิมต้องใช้ push ทุกข้อความ (นับโควตา LINE) เพราะ event ไม่มี reply token · ตอนนี้:
  - event พก `reply_token` + `channel_pk` เพิ่ม
  - `line_client.respond(access_token, reply_token, to, messages)` ลอง reply (ฟรี) ก่อน →
    fallback push อัตโนมัติ (โมดูลไม่ต้องรู้เรื่อง token หมดอายุ) · bridge ใช้ helper เดียวกันนี้แล้ว
  - ⚠️ reply_token ใช้ครั้งเดียว → หนึ่ง channel ควรมีผู้ตอบคนเดียว (จด README แล้ว)

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
