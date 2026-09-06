"""CLI ของโมดูล tenancy — cli.py หลัก mount ให้เป็น command group `tenancy` อัตโนมัติ
(เฉพาะเมื่อเปิดโมดูล tenancy ใน PSTACK_MODULES)

    python cli.py tenancy list
    python cli.py tenancy create acme --name "Acme Co"
    python cli.py tenancy add-member acme user@example.com --role owner
    python cli.py tenancy members acme

import ของ core/addon อยู่ในตัวคำสั่ง (ไม่ใช่ระดับ module) เพื่อให้การ mount ตอน CLI
boot ราคาถูก — งานหนักเกิดเฉพาะตอนรันคำสั่งจริง
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import typer

cli = typer.Typer(no_args_is_help=True, help="จัดการ tenant / member / workspace")


def _run(work: Callable[[Any], Awaitable[None]]) -> None:
    """boot app (ให้ทุกโมดูล import → metadata พร้อม) แล้วรัน work บน session เดียว"""
    from core.app import create_app

    create_app()
    from core.db import dispose_engine, get_sessionmaker

    async def _main() -> None:
        try:
            async with get_sessionmaker()() as session:
                await work(session)
        finally:
            await dispose_engine()

    asyncio.run(_main())


async def _resolve_user(session: Any, ref: str) -> Any:
    """หา user จากอีเมลหรือ id (ตัวเลข)"""
    from addons.users.models import User
    from addons.users.services import get_by_email

    ref = ref.strip()
    if ref.isdigit():
        return await session.get(User, int(ref))
    return await get_by_email(session, ref.lower())


@cli.command("list")
def list_tenants() -> None:
    """แสดง tenant ทั้งหมด"""

    async def work(session: Any) -> None:
        from sqlalchemy import select

        from addons.tenancy.models import Tenant

        rows = list(
            (await session.execute(select(Tenant).order_by(Tenant.tenant_id))).scalars()
        )
        if not rows:
            typer.echo("(ยังไม่มี tenant)")
            return
        for t in rows:
            typer.echo(f"{t.tenant_id:<24} {t.timezone:<16} {t.display_name}")

    _run(work)


@cli.command("create")
def create(
    tenant_id: str,
    name: str = typer.Option("", "--name", help="ชื่อแสดง"),
    timezone: str = typer.Option("Asia/Bangkok", "--timezone"),
) -> None:
    """สร้าง tenant ใหม่"""

    async def work(session: Any) -> None:
        from sqlalchemy.exc import IntegrityError

        from addons.tenancy import services
        from core.tenancy import InvalidId

        try:
            await services.create_tenant(session, tenant_id, name, timezone)
            await session.commit()
        except InvalidId as e:
            typer.secho(str(e), fg="red")
            raise typer.Exit(1) from e
        except IntegrityError as e:
            await session.rollback()
            typer.secho(f"tenant_id '{tenant_id}' มีอยู่แล้ว", fg="red")
            raise typer.Exit(1) from e
        typer.secho(f"สร้าง tenant '{tenant_id}' แล้ว", fg="green")

    _run(work)


@cli.command("add-member")
def add_member(
    tenant_id: str,
    user: str = typer.Argument(..., help="อีเมลหรือ user id"),
    role: str = typer.Option("member", "--role"),
) -> None:
    """เพิ่มผู้ใช้เข้า tenant (ระบุด้วยอีเมลหรือ id)"""

    async def work(session: Any) -> None:
        from sqlalchemy.exc import IntegrityError

        from addons.tenancy import services
        from addons.tenancy.models import Tenant

        u = await _resolve_user(session, user)
        if u is None:
            typer.secho(f"ไม่พบผู้ใช้ '{user}'", fg="red")
            raise typer.Exit(1)
        if await session.get(Tenant, tenant_id) is None:
            typer.secho(f"ไม่พบ tenant '{tenant_id}'", fg="red")
            raise typer.Exit(1)
        try:
            await services.add_member(session, tenant_id, u.id, role.strip() or "member")
            await session.commit()
        except IntegrityError as e:
            await session.rollback()
            typer.secho(f"{u.email} เป็นสมาชิกของ {tenant_id} อยู่แล้ว", fg="red")
            raise typer.Exit(1) from e
        typer.secho(
            f"เพิ่ม {u.email} (id={u.id}) เข้า {tenant_id} เป็น '{role}' แล้ว", fg="green"
        )

    _run(work)


@cli.command("members")
def members(tenant_id: str) -> None:
    """แสดงสมาชิกของ tenant"""

    async def work(session: Any) -> None:
        from sqlalchemy import select

        from addons.tenancy.models import TenantMember
        from addons.users.models import User

        rows = list(
            (
                await session.execute(
                    select(TenantMember)
                    .where(TenantMember.tenant_id == tenant_id)
                    .order_by(TenantMember.user_id)
                )
            ).scalars()
        )
        if not rows:
            typer.echo("(ไม่มีสมาชิก)")
            return
        for m in rows:
            u = await session.get(User, m.user_id)
            typer.echo(f"{m.user_id:<6} {m.role:<12} {u.email if u else '?'}")

    _run(work)
