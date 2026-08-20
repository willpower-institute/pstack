# คู่มือเขียนโมดูล pstack

เดินตามนี้ทีละขั้นได้เลย — ทุกขั้นมีของจริงให้ดูในโมดูล **`addons/faq/`** (โมดูลตัวอย่างที่ตั้งใจเขียนให้ครบทุก pattern)

## 0. สร้างโครง

```bash
python cli.py new-module myshop
# แล้วเพิ่ม myshop เข้า PSTACK_MODULES ใน .env
```

ได้โครงมาตรฐาน: `__manifest__.py`, `models.py`, `routes.py`, `hooks.py`, `templates/`, `static/`

## 1. Manifest — บัตรประชาชนของโมดูล

```python
# __manifest__.py — ต้องเป็น dict literal เท่านั้น (ระบบอ่านด้วย literal_eval ไม่ execute)
{
    "name": "myshop",
    "version": "1.0.0",          # ขยับเมื่อ schema/พฤติกรรมเปลี่ยน -> ระบบรัน on_upgrade ให้
    "depends": ["users"],        # kernel โหลด/ติดตั้งตามลำดับ dependency ให้เอง
    "permissions": ["myshop.read", "myshop.write"],   # ประกาศไว้เป็น convention
}
```

## 2. Models + Migration

```python
# models.py — ใช้ Base ของ kernel เสมอ
from core.db import Base

class Product(Base):
    __tablename__ = "myshop_products"   # แนะนำ prefix ชื่อโมดูลกันชนกับโมดูลอื่น
    ...
```

สร้าง migration แรก (และทุกครั้งที่แก้ schema):

```bash
python cli.py makemigration myshop -m "initial schema"
```

- แต่ละโมดูลมี lineage ของตัวเอง (`alembic_version_myshop`) — ไม่ชนกับโมดูลอื่น
- autogenerate มองเฉพาะตารางของโมดูลตัวเอง
- ไม่สร้าง migrations/ เลยก็ได้ — ระบบจะ create-table ให้ตอน install (เหมาะช่วง prototype)

## 3. Routes — API และหน้าเว็บ

```python
# routes.py — ต้องมีตัวแปรชื่อ router
from fastapi import APIRouter, Depends
from core.auth import get_current_user, require_permission
from core.templating import render

router = APIRouter(prefix="/api/myshop", tags=["myshop"])

@router.get("")                                       # สาธารณะ
async def list_products(...): ...

@router.post("", dependencies=[Depends(require_permission("myshop.write"))])
async def create_product(...): ...                    # ต้องมี permission
```

หน้า HTML: วางเทมเพลตใน `templates/` แล้วอ้างชื่อแบบ `"myshop/page.html"` — ดู `addons/faq/routes.py` (`/faq`) เป็นตัวอย่างหน้าเว็บสาธารณะเต็มๆ ไฟล์ static วางใน `static/` จะถูก mount ที่ `/static/myshop/` อัตโนมัติ

ถ้าต้องการทั้งหน้าเว็บ (path สั้น) และ API (ใต้ /api) ในโมดูลเดียว ใช้ sub-router — ดู `addons/ai_agent/routes.py`

## 4. Hooks — seed / upgrade

```python
# hooks.py
async def on_install(session):        # รันครั้งเดียวตอนติดตั้ง (หลังสร้างตารางแล้ว)
    ...  # seed ข้อมูลตั้งต้น — ดู addons/faq/hooks.py หรือ addons/users/hooks.py

async def on_upgrade(session, from_version):   # รันเมื่อ version ใน manifest ขยับ
    ...
```

## 5. AI Tools — จุดที่ทำให้โมดูลคุยกับ agent ได้

```python
# tools.py
from core.ai import agent_tool

@agent_tool(module="myshop", permission="myshop.read")
async def search_products(session, query: str) -> str:
    """ค้นหาสินค้าจากชื่อ"""      # docstring = สิ่งที่ agent ใช้ตัดสินใจเรียก
    ...
```

- อาร์กิวเมนต์แรกชื่อ `session` เสมอ (runtime ส่ง AsyncSession ให้)
- พารามิเตอร์อื่นต้องมี type hint (str/int/float/bool) — ใช้สร้าง JSON schema อัตโนมัติ
- `permission=None` = tool สาธารณะ — **guest ที่ทักผ่าน LINE ก็เรียกได้** (ดู `addons/faq/tools.py`)
- มี permission = เฉพาะ user ที่มีสิทธิ์นั้น (agent กรองให้ก่อนทุก turn)

## 6. Events — คุยข้ามโมดูลโดยไม่ผูกกัน

```python
from core.runtime import ctx

@ctx.events.on("line.message.received")        # subscribe (วางใน __init__.py หรือ services)
async def on_line_message(payload): ...

await ctx.events.emit("myshop.order.created", {"order_id": 1}, broadcast=True)
# broadcast=True -> ข้ามโปรเซสผ่าน Redis (เช่นถึง ARQ worker) — payload ต้องเป็น JSON ได้
```

## 7. Background jobs

```python
# jobs.py
from core.jobs import background_job

@background_job
async def rebuild_report(ctx, shop_id: int):   # ctx = arq context เสมอ
    ...

# สั่งงานจากที่ไหนก็ได้:  await enqueue("rebuild_report", shop_id=1)
```

**Periodic job (worker เดินลูปเอง เป็นระยะ):**

```python
from core.jobs import periodic_job

@periodic_job(minute=set(range(0, 60)))   # ทุกนาที (kwargs ส่งตรงให้ arq.cron)
async def care_tick(ctx):
    ...
# @periodic_job(hour={9}, minute={0})     # ทุกวัน 09:00

# worker เรียกเอง ไม่ต้อง enqueue — ต้องรัน `arq core.worker.WorkerSettings` (มีใน compose)
```

> ⏰ **cron ตีความด้วยเวลา UTC ของ container** — คำนวณ due time เป็น UTC ไว้ก่อนเสมอ
> (framework ยึด UTC: `datetime.now(UTC)`) · รัน worker หลาย replica ได้ arq coalesce cron ให้ยิงครั้งเดียว

## 8. เทส

เพิ่มโมดูลเข้า `PSTACK_MODULES` ใน `tests/test_smoke.py` แล้วเขียนเทสผ่าน `TestClient` — บูตจริงทั้งระบบบน sqlite (ไม่ต้องมี postgres/redis/API key) ดูตัวอย่างครบทุกแบบใน `tests/test_smoke.py`

**เทส async ที่แตะ DB เอง (โดยเฉพาะบน Postgres CI):** อย่าใช้ global engine — มันผูกกับ event loop ที่สร้างมัน เทสที่ใช้ loop ใหม่ต่อเทสจะเจอ `got Future attached to a different loop` บน asyncpg (aiosqlite เงียบ) ใช้ `core.testing.isolated_session` สร้าง engine แยกต่อเทส:

```python
import pytest_asyncio
from core.testing import isolated_session

@pytest_asyncio.fixture
async def db_session():
    async with isolated_session() as session:
        yield session
```

**ยืนยัน periodic job ไม่ถูกเผลอเปลี่ยน:** ใช้ public accessor `core.jobs.periodic_jobs()` / `background_jobs()` (คู่กับ `core.ai.get_tools()`) — เช่น `assert "care_tick" in [fn.__name__ for fn, _ in periodic_jobs()]` กันใครเปลี่ยน `@periodic_job` กลับเป็น `@background_job` แล้วลูปเงียบ

## 9. Multi-tenancy (v0.3.0+)

โมดูล `tenancy` ให้ control plane (`tenant`/`workspace`/`tenant_member`) · primitives ที่โมดูลโดเมนใช้อยู่ที่ **`core.tenancy`** (import ได้ทุกที่ ไม่ผูก path):

```python
from core.tenancy import TenantScope, scoped, assert_same_tenant, validate_id
from addons.tenancy.deps import ScopeDep, SessionDep       # dependency สำเร็จรูป

@router.get("/notes")
async def list_notes(scope: ScopeDep, session: SessionDep):   # ต้องส่ง header X-Tenant-Id
    stmt = scoped(select(Note), Note, scope)                  # เติม WHERE tenant_id ให้
    return (await session.execute(stmt)).scalars().all()
```

**สองด่านเสมอ:** `scoped()` = ด่าน app (query ทุกตัวต้องผ่าน) · **RLS = ด่าน DB กันพลาด** — เปิดที่ตารางข้อมูลโดเมนใน migration:

```python
from core.tenancy import rls_statements

def upgrade():
    op.create_table("note", ...)                    # ต้องมีคอลัมน์ tenant_id
    for stmt in rls_statements("note"):             # นอก guard has_table เสมอ
        op.execute(stmt)                            # ENABLE + FORCE + policy (idempotent)
```

> 🔴 **`docker-compose.yml` ที่แถมมาให้ app ต่อ DB ด้วย `${DB_USER}` ซึ่งเป็น bootstrap
> superuser ของ cluster (`rolsuper = t`, `rolbypassrls = t`) — RLS จะไม่มีผลเลยจนกว่าจะ
> สร้าง role แยก** · role ใหม่ต้อง **เป็นเจ้าของตาราง** ด้วย (ไม่ใช่แค่ read/write) เพราะ
> pstack รัน migration ตอนบูตด้วย connection เส้นเดียวกัน — ไม่งั้น app บูตไม่ขึ้น
> (`must be owner of table ...`) · owner ไม่ทำให้ RLS หลุดเพราะ `rls_statements()` ตั้ง `FORCE` ไว้ · ใช้ [`deploy/db-role.sql`](../deploy/db-role.sql) แล้วพิสูจน์ด้วย
> [`deploy/verify-rls.sh`](../deploy/verify-rls.sh) — อย่าเชื่อว่า RLS ทำงานเพราะ migration
> รันผ่าน มันรันผ่านเสมอ
>
> ⚠️ **RLS ถูก bypass เสมอโดย superuser role และ table owner ที่ไม่ตั้ง FORCE** — production **ห้าม**ให้ app เชื่อมต่อ DB ด้วย superuser · `rls_statements()` ตั้ง `FORCE ROW LEVEL SECURITY` ให้เพื่อบังคับกับ owner ด้วย · พิสูจน์ด้วย conformance test แบบ `tests/test_tenancy.py::test_rls_conformance_postgres`

#### ตั้ง GUC ให้ RLS: `bind_tenant()` ไม่ใช่ `set_tenant()`

`get_scope` เรียก **`bind_tenant(session, tenant_id)`** ให้อัตโนมัติต่อ request — มันผูก tenant ไว้กับ **session** แล้วตั้ง GUC ใหม่ทุกครั้งที่ transaction เริ่ม (ผ่าน event `after_begin`) จึง **รอดการ commit กลางทาง**

> 🔴 **`set_tenant()` ตั้ง GUC แค่ transaction เดียว — หายเมื่อ commit** · โค้ดที่ commit แล้วอ่านต่อ หรือ background job ที่วนหลาย tenant แล้ว commit ท้ายรอบ จะเห็น **0 แถวแบบเงียบ ๆ** (RLS deny-by-default ไม่มี error) · care เจอตอนเปิด RLS: เทส 42 ตัวกลายเป็น "ไม่พบผู้ป่วย" (care#4) — **ใช้ `bind_tenant()` เสมอเว้นแต่รู้แน่ว่าอยู่ transaction เดียว**

```python
# background job — bind ใหม่ต่อ tenant ในลูป
for tenant_id in tenant_ids:
    await bind_tenant(session, tenant_id)
    await do_work(session)         # เห็นเฉพาะ tenant นี้ แม้ commit ระหว่างทาง
    await session.commit()
```

#### background job หา tenant จากไหน — ตาราง control plane (ไม่มี RLS)

worker ที่ต้องวนทุก tenant **ห้าม** discover ด้วย `SELECT DISTINCT tenant_id FROM <ตารางโดเมนที่มี RLS>` — ณ จุดนั้นยังไม่มี GUC จะได้ 0 แถวเสมอ · อ่านจากตาราง **`tenant`** ของ kernel ที่ **ตั้งใจไม่เปิด RLS** (control plane) แทน:

```python
tenant_ids = (await session.execute(select(Tenant.tenant_id))).scalars().all()
```

### Runbook: adopt ตารางเดิมเข้า `tenancy` (deployment ที่มีข้อมูลแล้ว)

initial migration ของ `tenancy` เป็น **idempotent** — เจอตารางชื่อกลาง (`tenant`/`workspace`/`tenant_member`) อยู่แล้วจะข้าม create แล้วให้ alembic บันทึก revision เอง (ไม่ต้อง `stamp` มือ) · แต่ **ต้อง rename ของเดิมให้ครบก่อนเปิดโมดูล** และทำใน **transaction เดียว** (rename ล้มกลางคัน = สภาพผสม migration จะ `raise` เตือน):

```sql
BEGIN;
  -- precondition: ยังไม่ adopt + มีของเดิมให้ย้าย
  DO $$ BEGIN
    IF to_regclass('public.ap_tenant') IS NULL OR to_regclass('public.tenant') IS NOT NULL
    THEN RAISE EXCEPTION 'สภาพไม่พร้อม adopt'; END IF;
  END $$;
  ALTER TABLE ap_tenant        RENAME TO tenant;
  ALTER TABLE ap_workspace     RENAME TO workspace;
  ALTER TABLE ap_tenant_member RENAME TO tenant_member;
  -- ⚠️ ALTER TABLE ... RENAME TO เปลี่ยน "แค่ชื่อตาราง" — constraint/index/PK/FK คงชื่อเดิมไว้ทั้งหมด
  --    (Postgres **ไม่** ตั้งชื่อ <table>_pkey / _fkey ให้ใหม่ตอน rename) ต้อง rename ทุกตัวเองให้ตรง canonical
  ALTER TABLE tenant        RENAME CONSTRAINT ap_tenant_pkey                  TO tenant_pkey;
  ALTER TABLE workspace     RENAME CONSTRAINT ap_workspace_pkey               TO workspace_pkey;
  ALTER TABLE workspace     RENAME CONSTRAINT ap_workspace_tenant_id_fkey     TO workspace_tenant_id_fkey;
  ALTER TABLE tenant_member RENAME CONSTRAINT ap_tenant_member_pkey           TO tenant_member_pkey;
  ALTER TABLE tenant_member RENAME CONSTRAINT ap_tenant_member_tenant_id_fkey TO tenant_member_tenant_id_fkey;
  ALTER TABLE tenant_member RENAME CONSTRAINT uq_ap_member                    TO uq_tenant_member;
  ALTER INDEX ix_ap_workspace_tenant_id     RENAME TO ix_workspace_tenant_id;
  ALTER INDEX ix_ap_tenant_member_tenant_id RENAME TO ix_tenant_member_tenant_id;
  ALTER INDEX ix_ap_tenant_member_user_id   RENAME TO ix_tenant_member_user_id;
COMMIT;
```

> ชื่อ `ap_*` ด้านซ้ายคือของ consumer แต่ละราย — **สูตรทั่วไปคือ** "rename ทุก constraint/index ของ 3 ตารางให้ตรงชื่อ canonical ด้านล่าง" ไม่ใช่จำชื่อเฉพาะของใคร · หาชื่อเดิมของ deployment ตัวเองด้วย query นี้:
> ```sql
> SELECT conrelid::regclass AS tbl, conname FROM pg_constraint
>  WHERE conrelid = ANY(ARRAY['tenant','workspace','tenant_member']::regclass[])
> UNION ALL
> SELECT tablename::regclass, indexname FROM pg_indexes
>  WHERE tablename IN ('tenant','workspace','tenant_member');
> ```

ชื่อ canonical ที่ kernel freeze ไว้ (rename ให้ตรงเป๊ะ):

| ตาราง | PK | unique | index | FK |
|---|---|---|---|---|
| `tenant` | `tenant_pkey` | — | — | — |
| `workspace` | `workspace_pkey` | — | `ix_workspace_tenant_id` | `workspace_tenant_id_fkey` |
| `tenant_member` | `tenant_member_pkey` | `uq_tenant_member` | `ix_tenant_member_tenant_id`, `ix_tenant_member_user_id` | `tenant_member_tenant_id_fkey` |

จากนั้นเพิ่ม `tenancy` เข้า `PSTACK_MODULES` แล้วบูต — migration ข้าม create ให้เอง · **ถ้าชื่อ constraint/index ไม่ตรง canonical ตอน adopt migration จะ `raise` ทันที** (ตรวจบน Postgres) ไม่ปล่อยให้ไปพังเงียบ ๆ ที่ revision ถัดไป · `cli.py stamp <module>` มีไว้สำหรับเคส adopt อื่น/ซ่อม version table (โมดูล idempotent แบบ `tenancy` ไม่ต้องใช้)

## Checklist ก่อน merge

- [ ] `__manifest__.py` ระบุ `depends` ครบ (ขาดแล้วโมดูลจะโหลดก่อน dependency แล้วพัง)
- [ ] มี migration (`cli.py makemigration`) ถ้าโมดูลมีตาราง
- [ ] endpoint ที่แก้ข้อมูลมี `require_permission(...)` เสมอ
- [ ] tools มี docstring ภาษาชัดเจน + ตั้ง permission ถูก (None = ทุกคนรวม guest LINE)
- [ ] `pytest tests/` ผ่าน
