"""Unit tests สำหรับ primitives v0.3.0 — ไม่ต้องบูตทั้ง app

- core.clock (FakeClock, ปฏิเสธ naive)
- core.tenancy.ID_PATTERN เป็น contract lock กับ identity/v1 $defs.Id
- scoped()/assert_same_tenant บน sqlite (app-level isolation)
- migrations.stamp() — บันทึก version โดยไม่รัน migration
- RLS conformance — Postgres เท่านั้น (ตั้ง PSTACK_PG_TEST_URL ถึงจะรัน) = adopt gate
"""

import asyncio
import datetime
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest
import sqlalchemy as sa


def test_clock_fake_advance():
    from core.clock import FakeClock, now

    with FakeClock("2026-08-19T07:00:00+07:00") as clk:
        t0 = now()
        clk.advance(minutes=45)
        assert (now() - t0).total_seconds() == 45 * 60
    # ออกจาก context -> กลับใช้เวลาจริง
    assert (datetime.datetime.now(datetime.UTC) - now()).total_seconds() < 5


def test_clock_rejects_naive():
    from core.clock import set_now

    with pytest.raises(ValueError):
        set_now(datetime.datetime(2026, 1, 1))  # noqa: DTZ001 — จงใจ naive เพื่อทดสอบว่าถูกปฏิเสธ
    set_now(None)  # cleanup


def test_id_pattern_is_identity_v1_contract():
    """🔒 lock: pattern ต้องตรง identity/v1 $defs.Id — ถ้า diff แปลว่า drift จาก consumer"""
    from core.tenancy import ID_PATTERN, InvalidId, new_id, validate_id

    assert ID_PATTERN.pattern == r"^[a-z0-9][a-z0-9_-]{0,62}$"
    assert validate_id("tenant-abc_1") == "tenant-abc_1"
    for bad in ["", "-x", "Abc", "a" * 64, "a b", "_x"]:
        with pytest.raises(InvalidId):
            validate_id(bad)
    assert ID_PATTERN.match(new_id("grant"))  # new_id ออกมาตรง pattern เสมอ


def test_scoped_and_assert_same_tenant():
    from sqlalchemy import select

    from addons.tenancy.models import Tenant, TenantMember, Workspace
    from core.db import Base
    from core.tenancy import (
        Principal,
        TenantIsolationError,
        TenantScope,
        assert_same_tenant,
        scoped,
    )
    from core.testing import isolated_session

    async def _run():
        async with isolated_session("sqlite+aiosqlite:///:memory:") as s:
            conn = await s.connection()
            await conn.run_sync(
                lambda c: Base.metadata.create_all(
                    c,
                    tables=[Tenant.__table__, Workspace.__table__, TenantMember.__table__],
                )
            )
            s.add_all(
                [
                    Tenant(tenant_id="t-a"),
                    Tenant(tenant_id="t-b"),
                    TenantMember(tenant_id="t-a", user_id=1),
                    TenantMember(tenant_id="t-b", user_id=2),
                ]
            )
            await s.flush()

            scope_a = TenantScope(tenant_id="t-a", principal=Principal("human", "user-1"))
            rows = (
                await s.execute(scoped(select(TenantMember), TenantMember, scope_a))
            ).scalars().all()
            assert {r.tenant_id for r in rows} == {"t-a"}  # เห็นเฉพาะ tenant ตัวเอง
            assert_same_tenant(scope_a, rows[0])

            # หยิบแถวของ t-b มา assert ใน scope t-a -> ระเบิด
            other = (
                await s.execute(
                    select(TenantMember).where(TenantMember.tenant_id == "t-b")
                )
            ).scalar_one()
            with pytest.raises(TenantIsolationError):
                assert_same_tenant(scope_a, other)

    asyncio.run(_run())


def test_scoped_requires_tenant_column():
    from core.tenancy import Principal, TenantScope, scoped

    class NoTenant:
        pass

    scope = TenantScope(tenant_id="t-a", principal=Principal("human", "user-1"))
    with pytest.raises(TypeError):
        scoped(sa.select(sa.literal(1)), NoTenant, scope)


def test_stamp_writes_version_without_running_migration():
    """stamp บันทึก alembic_version_tenancy = head แต่ไม่สร้างตาราง tenant"""
    from sqlalchemy.ext.asyncio import create_async_engine

    from core import migrations
    from core.loader import discover

    info = discover(["addons"])["tenancy"]

    async def _run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            await migrations.stamp(engine, info)  # ไม่รัน migration
            async with engine.connect() as c:
                ver = (
                    await c.execute(
                        sa.text("SELECT version_num FROM alembic_version_tenancy")
                    )
                ).scalar_one()
                names = await c.run_sync(lambda cc: sa.inspect(cc).get_table_names())
            assert ver == "0001_tenancy_initial"
            assert "tenant" not in names  # stamp ไม่สร้างตาราง
            assert "alembic_version_tenancy" in names
        finally:
            await engine.dispose()

    asyncio.run(_run())


def _pg_url() -> str | None:
    return os.environ.get("PSTACK_PG_TEST_URL") or os.environ.get("PSTACK_PG_ADMIN_URL")


def test_rls_conformance_postgres():
    """adopt gate: FORCE RLS ทำให้ query ไม่มี WHERE เห็นแค่ tenant ของ GUC

    รันด้วย **connection ของแอปจริง** (`PSTACK_PG_TEST_URL`) — role ที่ deployment ใช้ต่อ DB จริง
    ไม่ใช่ superuser ที่สร้าง role/SET ROLE เอง (เวอร์ชันก่อนผ่านได้เฉพาะ role ที่ deployment
    ไม่ควรมี — care ชี้ว่าผลไม่ตอบคำถามเดิม) เทสนี้จึง:

    1. ยืนยันก่อนว่า role นี้ **ไม่ bypass RLS** (rolsuper=false, rolbypassrls=false)
       — ถ้า bypass แปลว่า gate ตอบไม่ได้ → fail ทันที (พับ db_role_check ของ care เข้ามา)
    2. สร้างตารางที่ role นี้เป็น **owner** เอง แล้วพิสูจน์ว่า FORCE บังคับ RLS กับ owner จริง

    ไม่ต้องใช้ superuser/CREATE ROLE — role ของแอปสร้าง+เปิด RLS บนตารางของตัวเองได้
    (ต้องมีสิทธิ์ CREATE บน schema — deployment ให้ไว้อยู่แล้ว)
    """
    pg = os.environ.get("PSTACK_PG_TEST_URL")
    if not pg:
        pytest.skip("ตั้ง PSTACK_PG_TEST_URL (connection ของแอปจริง) เพื่อรัน RLS conformance")

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from core.tenancy import TENANT_GUC, rls_statements, set_tenant

    async def _run():
        engine = create_async_engine(pg)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as s:
                # (1) gate ตัวจริง: role ที่ใช้ต่อ DB ต้องไม่ bypass RLS ไม่งั้นผลไม่มีความหมาย
                role, is_super, is_bypass = (
                    await s.execute(
                        sa.text(
                            "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles "
                            "WHERE rolname = current_user"
                        )
                    )
                ).one()
                if is_super or is_bypass:
                    pytest.fail(
                        f"role '{role}' bypass RLS (super={is_super} bypassrls={is_bypass}) — "
                        "RLS ไร้ผลกับ role นี้ · deployment ต้องต่อ DB ด้วย role "
                        "NOSUPERUSER NOBYPASSRLS ไม่งั้น gate ตอบไม่ได้"
                    )

                # (2) role นี้เป็น owner ตารางเอง → FORCE คือสิ่งที่ทำให้ RLS บังคับกับ owner
                await s.execute(sa.text("DROP TABLE IF EXISTS conf_note"))
                await s.execute(
                    sa.text(
                        "CREATE TABLE conf_note (id serial PRIMARY KEY, "
                        "tenant_id text NOT NULL, body text)"
                    )
                )
                for stmt in rls_statements("conf_note"):
                    await s.execute(sa.text(stmt))
                await s.commit()

                # insert 2 tenant — ต้องตั้ง GUC ให้ตรงก่อน (USING เป็น WITH CHECK ของ INSERT ด้วย)
                await set_tenant(s, "t-a")
                await s.execute(
                    sa.text("INSERT INTO conf_note (tenant_id, body) VALUES ('t-a','a1')")
                )
                await set_tenant(s, "t-b")
                await s.execute(
                    sa.text("INSERT INTO conf_note (tenant_id, body) VALUES ('t-b','b1')")
                )
                await s.commit()

                # GUC = t-a: SELECT ไม่มี WHERE ต้องเห็นแค่ t-a (FORCE บังคับกับ owner)
                await set_tenant(s, "t-a")
                rows = (
                    await s.execute(sa.text("SELECT tenant_id FROM conf_note"))
                ).scalars().all()
                assert set(rows) == {"t-a"}, rows

                # GUC ว่าง -> deny by default -> 0 แถว
                await s.execute(sa.text(f"SELECT set_config('{TENANT_GUC}', '', true)"))
                empty = (
                    await s.execute(sa.text("SELECT count(*) FROM conf_note"))
                ).scalar_one()
                assert empty == 0

                await s.execute(sa.text("DROP TABLE conf_note"))
                await s.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_create_tenant_on_postgres():
    """regression (#1 จาก care): สร้าง tenant ผ่าน services บน Postgres จริง

    เทสเดิมพลาดบั๊กนี้เพราะ tests/ รันบน sqlite (เก็บ datetime เป็น string ไม่สน tz) และ
    conformance test สร้างตารางด้วย raw SQL ไม่ผ่าน ORM ของ tenancy · เทสนี้เดิน path จริง
    (migration สร้างตาราง → services.create_tenant เขียนผ่าน ORM) จับ aware/naive mismatch ได้
    """
    pg = _pg_url()
    if not pg:
        pytest.skip("ตั้ง PSTACK_PG_TEST_URL เพื่อรัน (Postgres เท่านั้น)")

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from addons.tenancy import services
    from core import migrations
    from core.loader import discover

    info = discover(["addons"])["tenancy"]

    async def _run():
        engine = create_async_engine(pg)
        try:
            # เริ่มจาก schema สะอาด แล้วสร้างตารางผ่าน "migration จริง" (ไม่ใช่ create_all)
            async with engine.begin() as c:
                for t in ("tenant_member", "workspace", "tenant"):
                    await c.execute(sa.text(f"DROP TABLE IF EXISTS {t} CASCADE"))
                await c.execute(sa.text("DROP TABLE IF EXISTS alembic_version_tenancy"))
            await migrations.upgrade_to_head(engine, info)

            async with async_sessionmaker(engine, expire_on_commit=False)() as s:
                t = await services.create_tenant(s, "pg-clinic", "PG Clinic")
                await s.commit()
                # อ่านกลับ — created_at ต้องเป็น aware (timezone=True) ไม่ใช่ naive
                assert t.tenant_id == "pg-clinic"
                assert t.created_at.tzinfo is not None

            async with engine.begin() as c:
                for t in ("tenant_member", "workspace", "tenant"):
                    await c.execute(sa.text(f"DROP TABLE IF EXISTS {t} CASCADE"))
                await c.execute(sa.text("DROP TABLE IF EXISTS alembic_version_tenancy"))
        finally:
            await engine.dispose()

    asyncio.run(_run())
