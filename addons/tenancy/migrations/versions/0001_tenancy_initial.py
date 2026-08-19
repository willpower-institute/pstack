"""tenancy initial — tenant / workspace / tenant_member (idempotent adopt-safe)

Revision ID: 0001_tenancy_initial
Revises:
Create Date: 2026-08-19

── idempotent adopt (issue #3) ──────────────────────────────────────────────
create_table แต่ละตัวอยู่ใต้ guard has_table บน **ชื่อของ kernel เอง** — deploy ใหม่
สร้างครบ, deployment ที่ rename ตารางเดิม (ap_tenant→tenant ฯลฯ) มาก่อนบูต จะข้าม
create แล้ว alembic บันทึก revision ให้เอง (ไม่ต้อง stamp มือ, kernel ไม่รู้จัก `ap_`)

ชื่อ constraint/index ตั้ง **explicit** ให้ตรงกับ deploy ใหม่เป๊ะ — deployment ที่
adopt ต้อง rename constraint+index ให้ตรงชุดนี้ด้วย (ดู runbook ใน docs/MODULE_GUIDE.md)
ไม่งั้น revision ถัดไปที่ drop_constraint จะพังเฉพาะที่ adopt

🔒 3 ตารางนี้เป็น control plane — **ไม่เปิด RLS** (ถ้าเปิด จะอ่าน membership เพื่อ
   สร้าง scope ไม่ได้ = ตายตอนบูต) RLS ใช้กับตารางข้อมูลโดเมนผ่าน core.tenancy.rls_statements()
"""
import sqlalchemy as sa
from alembic import op

revision = "0001_tenancy_initial"
down_revision = None
branch_labels = None
depends_on = None

TABLES = ("tenant", "workspace", "tenant_member")

# ชื่อ constraint/index ที่ kernel freeze ไว้ — deployment ที่ adopt ต้อง rename ให้ตรงชุดนี้
# (rename ตารางไม่ rename constraint/index ให้ · Postgres ตั้ง pk/fk เป็น <ตารางเดิม>_* ค้างไว้)
# revision ถัดไปที่ drop_constraint จะพังเฉพาะ deployment ที่ adopt ถ้าชื่อไม่ตรง → guard ตอน adopt เลย
CANONICAL_NAMES = {
    "tenant": {"tenant_pkey"},
    "workspace": {"workspace_pkey", "workspace_tenant_id_fkey", "ix_workspace_tenant_id"},
    "tenant_member": {
        "tenant_member_pkey",
        "tenant_member_tenant_id_fkey",
        "uq_tenant_member",
        "ix_tenant_member_tenant_id",
        "ix_tenant_member_user_id",
    },
}


def _actual_names(insp, table: str) -> set[str]:
    names: set[str] = set()
    pk = insp.get_pk_constraint(table).get("name")
    if pk:
        names.add(pk)
    for fk in insp.get_foreign_keys(table):
        if fk.get("name"):
            names.add(fk["name"])
    for uq in insp.get_unique_constraints(table):
        if uq.get("name"):
            names.add(uq["name"])
    for ix in insp.get_indexes(table):
        if ix.get("name"):
            names.add(ix["name"])
    return names


def _assert_canonical_names(insp) -> None:
    """ตอน adopt: ตารางครบแต่ชื่อ constraint/index อาจไม่ตรง canonical (runbook พาไปผิดได้ง่าย)
    ตรวจบน Postgres แล้ว raise พร้อมรายชื่อที่ขาด — กันไม่ให้เจ็บทีหลังตอน revision ถัดไป
    """
    missing: list[str] = []
    for table, expected in CANONICAL_NAMES.items():
        actual = _actual_names(insp, table)
        missing += sorted(expected - actual)
    if missing:
        raise RuntimeError(
            "tenancy adopt: ชื่อ constraint/index ไม่ตรง canonical ของ kernel — ขาด "
            f"{missing}\n"
            "rename ตารางไม่ rename constraint/index ให้ · rename ให้ครบใน transaction เดียว "
            "ก่อนบูต (ดูสูตร + query ตรวจใน docs/MODULE_GUIDE.md §9)"
        )


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    present = [t for t in TABLES if insp.has_table(t)]
    # guard: adopt ไม่ครบ (บางตารางมี บางตารางไม่มี) — มักเป็นเพราะ rename ล้มกลางคัน
    # ควร atomic ทั้ง 3 ตารางใน transaction เดียว (ดู runbook) — ถ้าถึงตรงนี้แปลว่าพลาด
    if present and len(present) != len(TABLES):
        missing = [t for t in TABLES if t not in present]
        raise RuntimeError(
            f"tenancy adopt ไม่สมบูรณ์: เจอ {present} แต่ขาด {missing} — "
            "rename ให้ครบทั้ง 3 ตารางใน transaction เดียวก่อนบูต (docs/MODULE_GUIDE.md)"
        )

    # ตารางครบทั้ง 3 = adopt (ไม่ใช่ deploy ใหม่) — ตรวจชื่อ canonical บน Postgres
    if len(present) == len(TABLES) and bind.dialect.name == "postgresql":
        _assert_canonical_names(insp)

    if not insp.has_table("tenant"):
        op.create_table(
            "tenant",
            sa.Column("tenant_id", sa.String(63), primary_key=True),
            sa.Column("display_name", sa.String(255), nullable=False, server_default=""),
            sa.Column(
                "timezone", sa.String(64), nullable=False, server_default="Asia/Bangkok"
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )

    if not insp.has_table("workspace"):
        op.create_table(
            "workspace",
            sa.Column("workspace_id", sa.String(63), primary_key=True),
            sa.Column("tenant_id", sa.String(63), nullable=False),
            sa.Column("display_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["tenant_id"],
                ["tenant.tenant_id"],
                name="workspace_tenant_id_fkey",
                ondelete="CASCADE",
            ),
        )
        op.create_index("ix_workspace_tenant_id", "workspace", ["tenant_id"])

    if not insp.has_table("tenant_member"):
        op.create_table(
            "tenant_member",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("tenant_id", sa.String(63), nullable=False),
            sa.Column("user_id", sa.Integer, nullable=False),
            sa.Column("role", sa.String(32), nullable=False, server_default="member"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["tenant_id"],
                ["tenant.tenant_id"],
                name="tenant_member_tenant_id_fkey",
                ondelete="CASCADE",
            ),
            sa.UniqueConstraint("tenant_id", "user_id", name="uq_tenant_member"),
        )
        op.create_index("ix_tenant_member_tenant_id", "tenant_member", ["tenant_id"])
        op.create_index("ix_tenant_member_user_id", "tenant_member", ["user_id"])


def downgrade() -> None:
    op.drop_table("tenant_member")
    op.drop_table("workspace")
    op.drop_table("tenant")
