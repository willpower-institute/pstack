-- สร้าง DB role สำหรับให้ app ใช้เชื่อมต่อ — **ห้ามใช้ role เดียวกับ POSTGRES_USER**
--
-- ทำไม: POSTGRES_USER ที่ตั้งใน docker-compose คือ bootstrap superuser ของ cluster
-- (rolsuper = t, rolbypassrls = t) ซึ่ง Postgres ยกเว้น RLS ให้เสมอ
-- ต่อให้ migration เปิด ENABLE + FORCE ROW LEVEL SECURITY ครบทุกตาราง
-- policy ก็จะไม่มีผลอะไรเลย — ข้อมูลข้าม tenant มองเห็นกันได้หมด
--
-- ⚠️ role นี้ต้อง **เป็นเจ้าของตาราง** ด้วย ไม่ใช่แค่มีสิทธิ์อ่าน/เขียน
--    เพราะ pstack รัน alembic migration ตอนบูตด้วย PSTACK_DATABASE_URL เส้นเดียวกัน
--    role ที่ไม่ได้เป็น owner จะทำให้ app **บูตไม่ขึ้น** ทันทีที่มี migration ใหม่:
--      InsufficientPrivilegeError: must be owner of table agent_sessions
--      ERROR:    Application startup failed. Exiting.
--
--    การเป็น owner ไม่ทำให้ RLS หลุด เพราะ core.tenancy.rls_statements() ตั้ง
--    FORCE ROW LEVEL SECURITY ไว้ ซึ่งบังคับ policy กับ owner ด้วย (ทดสอบยืนยันแล้ว)
--    สิ่งที่ห้ามคือ **superuser** — คนละเรื่องกับ owner
--
-- วิธีใช้:
--   1. แก้รหัสผ่านด้านล่างก่อน
--   2. docker compose exec -T db psql -U $DB_USER -d $DB_NAME < deploy/db-role.sql
--   3. แก้ PSTACK_DATABASE_URL ใน .env ให้ชี้มาที่ role นี้
--   4. docker compose up -d && ./deploy/verify-rls.sh <ตาราง> <tenant_id>

CREATE ROLE pstack_app LOGIN PASSWORD 'เปลี่ยนรหัสนี้ก่อนใช้จริง';

-- CREATE = สร้างตารางใหม่ตอน migration ได้
GRANT USAGE, CREATE ON SCHEMA public TO pstack_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO pstack_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO pstack_app;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO pstack_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO pstack_app;

-- โอนความเป็นเจ้าของของที่มีอยู่แล้วให้ role นี้ (ALTER TABLE ตอน migration ต้องใช้)
-- deployment ใหม่ที่ยังไม่มีตารางเลย ลูปนี้จะไม่ทำอะไร
DO $$
DECLARE r record;
BEGIN
  FOR r IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
    EXECUTE format('ALTER TABLE public.%I OWNER TO pstack_app', r.tablename);
  END LOOP;
  FOR r IN SELECT sequencename FROM pg_sequences WHERE schemaname = 'public' LOOP
    EXECUTE format('ALTER SEQUENCE public.%I OWNER TO pstack_app', r.sequencename);
  END LOOP;
END $$;

-- ต้องได้ f ทั้งสองคอลัมน์ — owner ได้ แต่ superuser ไม่ได้
SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'pstack_app';
