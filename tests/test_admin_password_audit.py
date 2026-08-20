"""ตรวจรหัส admin ที่อยู่ใน DB จริง ไม่ใช่แค่ค่าใน .env

PSTACK_ADMIN_PASSWORD ใช้แค่ตอนสร้าง admin คนแรก — deployment ที่ติดตั้งไว้ก่อน
มีการบังคับ อาจยังใช้ admin/admin อยู่แม้จะแก้ .env ไปแล้ว การเช็คค่าใน .env
จึงให้ความรู้สึกปลอดภัยผิด ๆ ต้องเช็ค hash ที่เก็บไว้จริง
"""

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from addons.users import hooks
from addons.users import services as user_services
from core.auth import hash_password


class _FakeUser:
    def __init__(self, password: str) -> None:
        self.password_hash = hash_password(password)


def _run_upgrade(monkeypatch, stored_password: str | None):
    async def fake_get_by_email(session, email):
        return None if stored_password is None else _FakeUser(stored_password)

    monkeypatch.setattr(user_services, "get_by_email", fake_get_by_email)
    asyncio.run(hooks.on_upgrade(session=None, from_version="1.0.0"))


def test_alerts_when_stored_admin_password_is_weak(monkeypatch, caplog):
    with caplog.at_level("ERROR"):
        _run_upgrade(monkeypatch, "admin")
    messages = [r.getMessage() for r in caplog.records]
    assert any("set-password" in m for m in messages), (
        f"ต้องบอกวิธีแก้ด้วย ไม่ใช่แค่บอกว่ามีปัญหา — ได้: {messages}"
    )


def test_quiet_when_stored_admin_password_is_strong(monkeypatch, caplog):
    with caplog.at_level("ERROR"):
        _run_upgrade(monkeypatch, "a-properly-long-admin-password")
    assert not [r for r in caplog.records if "set-password" in r.getMessage()]


def test_quiet_when_admin_account_does_not_exist(monkeypatch, caplog):
    with caplog.at_level("ERROR"):
        _run_upgrade(monkeypatch, None)
    assert not [r for r in caplog.records if "set-password" in r.getMessage()]
