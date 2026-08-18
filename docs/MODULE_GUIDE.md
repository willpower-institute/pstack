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

# worker เรียกเอง ไม่ต้อง enqueue — ต้องรัน `python -m arq core.worker.WorkerSettings` (มีใน compose)
```

> ⏰ **cron ตีความด้วยเวลา UTC ของ container** — คำนวณ due time เป็น UTC ไว้ก่อนเสมอ
> (framework ยึด UTC: `datetime.now(UTC)`) · รัน worker หลาย replica ได้ arq coalesce cron ให้ยิงครั้งเดียว

## 8. เทส

เพิ่มโมดูลเข้า `PSTACK_MODULES` ใน `tests/test_smoke.py` แล้วเขียนเทสผ่าน `TestClient` — บูตจริงทั้งระบบบน sqlite (ไม่ต้องมี postgres/redis/API key) ดูตัวอย่างครบทุกแบบใน `tests/test_smoke.py`

## Checklist ก่อน merge

- [ ] `__manifest__.py` ระบุ `depends` ครบ (ขาดแล้วโมดูลจะโหลดก่อน dependency แล้วพัง)
- [ ] มี migration (`cli.py makemigration`) ถ้าโมดูลมีตาราง
- [ ] endpoint ที่แก้ข้อมูลมี `require_permission(...)` เสมอ
- [ ] tools มี docstring ภาษาชัดเจน + ตั้ง permission ถูก (None = ทุกคนรวม guest LINE)
- [ ] `pytest tests/` ผ่าน
