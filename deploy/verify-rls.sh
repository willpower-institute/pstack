#!/usr/bin/env bash
# ตรวจว่า RLS ทำงานจริงหรือเป็นแค่ของประดับ — รันหลังตั้ง role ตาม deploy/db-role.sql
#
# ใช้: ./deploy/verify-rls.sh <ตารางที่มี tenant_id> <tenant_id ที่มีข้อมูลอยู่>
#      APP_DB_USER=pstack_app APP_DB_PASSWORD=... ./deploy/verify-rls.sh appointment t-demo
set -euo pipefail

TABLE="${1:?ระบุชื่อตาราง}"
TENANT="${2:?ระบุ tenant_id}"
OWNER_USER="${DB_USER:-pstack}"
DB_NAME="${DB_NAME:-pstack}"
APP_USER="${APP_DB_USER:-pstack_app}"

psql_owner() { docker compose exec -T db psql -U "$OWNER_USER" -d "$DB_NAME" "$@"; }
psql_app() {
  docker compose exec -T -e PGPASSWORD="${APP_DB_PASSWORD:?ตั้ง APP_DB_PASSWORD ก่อน}" \
    db psql -U "$APP_USER" -h 127.0.0.1 -d "$DB_NAME" "$@"
}

echo "== 1. role ที่ app ใช้ต่อ ต้องไม่ใช่ superuser (ต้องได้ f ทั้งคู่) =="
psql_owner -c "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname IN ('$OWNER_USER','$APP_USER');"

echo "== 2. ตาราง $TABLE ต้องเปิด RLS + FORCE (ต้องได้ t ทั้งคู่) =="
psql_owner -c "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname='$TABLE';"

echo "== 3. policy ต้องมีจริง =="
psql_owner -c "SELECT polname, pg_get_expr(polqual, polrelid) FROM pg_policy WHERE polrelid='$TABLE'::regclass;"

echo "== 4. ตั้ง GUC = $TENANT แล้ว select — ต้องเห็นเฉพาะแถวของ $TENANT =="
psql_app -c "SELECT set_config('pstack.tenant_id','$TENANT',false); SELECT tenant_id, count(*) FROM $TABLE GROUP BY tenant_id;"

echo "== 5. ไม่ตั้ง GUC — ต้องเห็น 0 แถว (deny by default) =="
psql_app -c "SELECT count(*) AS rows_visible FROM $TABLE;"

echo "== 6. role ต้องเป็นเจ้าของตาราง ไม่งั้น app บูตไม่ขึ้นตอนมี migration ใหม่ =="
psql_owner -c "SELECT tablename, tableowner FROM pg_tables WHERE schemaname='public' AND tableowner <> '$APP_USER' LIMIT 5;"
echo "   (ต้องได้ 0 rows — ถ้ามีรายชื่อโผล่มา ให้รัน deploy/db-role.sql ซ้ำ)"
