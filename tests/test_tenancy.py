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


def test_rls_conformance_postgres():
    """adopt gate: FORCE RLS ทำให้ query ไม่มี WHERE เห็นแค่ tenant ของ GUC — แม้เป็น owner

    รันเฉพาะเมื่อมี Postgres (ตั้ง PSTACK_PG_TEST_URL) — sqlite ไม่มี RLS
    ทีมรันเทสนี้บน deployment ที่ adopt แล้ว = พิสูจน์ว่าเงื่อนไข ก. ทำงานจริง

    ⚠️ สำคัญ: RLS **ถูก bypass เสมอ** โดย superuser และโดย table owner ที่ไม่ได้ตั้ง FORCE
       เทสจึงเชื่อมต่อในบทบาท role ธรรมดา (SET ROLE) ที่เป็น owner ของตาราง —
       FORCE ROW LEVEL SECURITY คือสิ่งเดียวที่ทำให้ policy บังคับกับ owner ด้วย
       👉 production ห้ามให้ app เชื่อมต่อด้วย superuser role ไม่งั้น RLS ไร้ผล
    """
    pg = os.environ.get("PSTACK_PG_TEST_URL")
    if not pg:
        pytest.skip("ตั้ง PSTACK_PG_TEST_URL เพื่อรัน RLS conformance (Postgres เท่านั้น)")

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from core.tenancy import TENANT_GUC, rls_statements, set_tenant

    async def _run():
        engine = create_async_engine(pg)
        try:
            # setup ในบทบาท superuser: สร้าง role ธรรมดา + ตาราง แล้วโอน ownership ให้ role นั้น
            async with engine.begin() as c:
                await c.execute(sa.text("DROP TABLE IF EXISTS conf_note"))
                await c.execute(sa.text("DROP ROLE IF EXISTS pstack_app"))
                await c.execute(sa.text("CREATE ROLE pstack_app NOSUPERUSER"))
                await c.execute(
                    sa.text(
                        "CREATE TABLE conf_note (id serial PRIMARY KEY, "
                        "tenant_id text NOT NULL, body text)"
                    )
                )
                for stmt in rls_statements("conf_note"):
                    await c.execute(sa.text(stmt))
                # โอน ownership ให้ role ธรรมดา (รวม sequence ที่เป็นเจ้าของ) — จำลอง production
                await c.execute(sa.text("ALTER TABLE conf_note OWNER TO pstack_app"))

            async with async_sessionmaker(engine, expire_on_commit=False)() as s:
                # ทำงานในบทบาท role ธรรมดา (owner + FORCE) — RLS บังคับจริง
                await s.execute(sa.text("SET ROLE pstack_app"))

                # insert 2 tenant — ต้องตั้ง GUC ให้ตรงก่อน (USING เป็น WITH CHECK ของ INSERT ด้วย)
                await set_tenant(s, "t-a")
                await s.execute(
                    sa.text("INSERT INTO conf_note (tenant_id, body) VALUES ('t-a','a1')")
                )
                await set_tenant(s, "t-b")
                await s.execute(
                    sa.text("INSERT INTO conf_note (tenant_id, body) VALUES ('t-b','b1')")
                )
                await s.commit()  # is_local GUC ล้างตอน commit, SET ROLE ยังอยู่

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

                await s.execute(sa.text("RESET ROLE"))  # กัน SET ROLE ค้างใน pooled conn
                await s.commit()  # SET/RESET ROLE เป็น transactional — ต้อง commit ไม่งั้น rollback คืนค่า
        finally:
            await engine.dispose()

        # cleanup ด้วย engine ใหม่ (connection สะอาด บทบาท superuser แน่นอน)
        cleanup = create_async_engine(pg)
        try:
            async with cleanup.begin() as c:
                await c.execute(sa.text("DROP TABLE IF EXISTS conf_note"))
                await c.execute(sa.text("DROP ROLE IF EXISTS pstack_app"))
        finally:
            await cleanup.dispose()

    asyncio.run(_run())
