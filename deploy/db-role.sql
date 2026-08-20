-- สร้าง DB role สำหรับให้ app ใช้เชื่อมต่อ — **ห้ามใช้ role เดียวกับ POSTGRES_USER**
--
-- ทำไม: POSTGRES_USER ที่ตั้งใน docker-compose คือ bootstrap superuser ของ cluster
-- (rolsuper = t, rolbypassrls = t) ซึ่ง Postgres ยกเว้น RLS ให้เสมอ
-- ต่อให้ migration เปิด ENABLE + FORCE ROW LEVEL SECURITY ครบทุกตาราง
-- policy ก็จะไม่มีผลอะไรเลย — ข้อมูลข้าม tenant มองเห็นกันได้หมด
--
-- วิธีใช้:
--   1. docker compose exec -T db psql -U $DB_USER -d $DB_NAME < deploy/db-role.sql
--   2. แก้ PSTACK_DATABASE_URL ใน .env ให้ชี้มาที่ role นี้
--      PSTACK_DATABASE_URL=postgresql+asyncpg://pstack_app:<รหัส>@db:5432/pstack
--   3. docker compose up -d && ./deploy/verify-rls.sh <ตาราง> <tenant_id>
--
-- role นี้แก้ข้อมูลได้แต่ไม่ได้เป็นเจ้าของตาราง — migration ยังรันด้วย role เดิม
-- (ตอนบูต app จะรัน migration ก่อน ถ้าใช้ role นี้รัน migration ด้วยต้อง GRANT CREATE เพิ่ม)

CREATE ROLE pstack_app LOGIN PASSWORD 'เปลี่ยนรหัสนี้ก่อนใช้จริง';

GRANT USAGE ON SCHEMA public TO pstack_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO pstack_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO pstack_app;

-- ตารางที่ migration ของโมดูลสร้างขึ้นทีหลังก็ต้องได้สิทธิ์ด้วย
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO pstack_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO pstack_app;

-- ต้องได้ f ทั้งสองคอลัมน์ ไม่งั้น RLS ยังถูก bypass อยู่
SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'pstack_app';
