# แนวทางย้ายโปรเจกต์เก่ามา pstack

เป้าหมาย: โปรเจกต์ FastAPI เดี่ยวๆ ที่มีอยู่ (เช่น `network-pupanha`, `network-watjan`)
ย้ายมาเป็น **addon หนึ่งตัว** บน pstack ได้โดยแก้โค้ดน้อยที่สุด

## Pattern ของโปรเจกต์เก่า (baseline)

```
app/
  main.py         FastAPI app + mount routers/static + lifespan (create_all + seed)
  config.py       pydantic-settings จาก .env
  database.py     SQLAlchemy engine / SessionLocal / Base
  models.py       SQLAlchemy 2.0 models
  routers/        APIRouter แยกตามเรื่อง
  templates/      Jinja2 (UI เป็น server-rendered + เปิดผ่าน LIFF)
  static/         css / js / รูป
  line_bot.py     LINE webhook เขียนเอง (verify signature, quick reply, reply API)
  ai_bot.py       (บางโปรเจกต์) AI ตอบแชท — ดึงข้อมูลจาก DB มาเป็น context
  seed.py         ข้อมูลตั้งต้น
sql/init.sql      รันครั้งเดียวตอนสร้าง volume DB
```

## ตารางแปลง: ของเก่า → ของใหม่

| ของเดิม | ย้ายไปที่ | หมายเหตุ |
|---|---|---|
| `models.py` | `addons/<name>/models.py` | SQLAlchemy 2.0 อยู่แล้ว — copy แทบตรงๆ เปลี่ยน Base เป็นของ kernel |
| `routers/*` | `addons/<name>/routes.py` | APIRouter mount อัตโนมัติ, auth เปลี่ยนมาใช้ RBAC ของ kernel |
| `templates/` `static/` | `addons/<name>/templates/` `static/` | kernel มี namespaced Jinja2 loader + auto static mount |
| `config.py` (.env) | module settings namespace | prefix ต่อโมดูล เช่น `PUPANHA_...` |
| `seed.py` + `sql/init.sql` | `hooks.py: on_install()` | รันซ้ำได้ ผูกกับ module lifecycle ไม่ใช่ volume DB |
| `line_bot.py` | **ลบทิ้ง** — ใช้โมดูล `line_oa` | channel + LIFF ID เป็น config ใน DB; เมนู quick reply เป็น data |
| `ai_bot.py` (Gemini) | **ลบทิ้ง** — ใช้โมดูล `ai_agent` | context จาก DB เปลี่ยนเป็น tools (`search_faq`, `search_products`, ...) ให้ agent เรียกเอง |
| `Base.metadata.create_all` | Alembic migration ต่อโมดูล | สร้างจาก models เดิมได้ด้วย `alembic revision --autogenerate` |
| docker-compose ต่อโปรเจกต์ | compose ของ pstack | ยังอยู่หลัง Caddy / `odoo-public` เหมือนเดิม |

## ข้อมูลใน DB เดิม

- ตาราง schema แทบไม่เปลี่ยน → `pg_dump --data-only` จาก DB เก่า → restore เข้า DB ของ pstack
- สิ่งที่เพิ่ม: FK ไปตาราง `users` กลาง (ถ้าเดิมมี user/admin ของตัวเอง) และคอลัมน์ audit มาตรฐาน

## ลำดับการย้าย (ต่อหนึ่งโปรเจกต์)

1. `pstack new-module <name>` — สร้างโครง addon
2. ย้าย models → สร้าง migration → ตรวจ schema ตรงกับของเดิม
3. ย้าย routers + templates + static → เทสหน้าเว็บ/LIFF
4. ตั้งค่า LINE channel ในโมดูล `line_oa` (token/secret/LIFF IDs ของ OA เดิม) → ชี้ webhook URL ใหม่
5. เขียน tools ให้ agent (แทน context dump ของ `ai_bot.py`) → เทสแชท
6. `pg_dump/restore` ข้อมูล → เทสรวม → สลับ vhost ใน Caddy มาที่ pstack

## สิ่งที่ kernel ต้องมีเพื่อรองรับ (design requirements)

- [ ] Namespaced Jinja2 template loader (โมดูลละโฟลเดอร์ + override ข้ามโมดูลได้)
- [ ] Auto static mount ต่อโมดูล (`/static/<module>/...`)
- [ ] Module settings namespace จาก .env
- [ ] `on_install` / `on_upgrade` hooks สำหรับ seed + data migration
- [ ] `line_oa`: หลาย channel, LIFF ID ต่อ channel, quick-reply menu เป็น data
- [ ] `ai_agent`: tool registry ที่โมดูลลงทะเบียน tools ค้นข้อมูลของตัวเองได้
