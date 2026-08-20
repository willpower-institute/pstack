"""กันเดารหัสผ่านที่ /api/auth/login

เดิมไม่มีอะไรกันเลยทั้ง repo — ยิงรหัสผิด 30 ครั้งรวดได้ 401 ทุกครั้งไม่มีหน่วง
และ bcrypt กิน CPU ~300ms ต่อครั้ง จึงใช้ถล่ม CPU ได้ด้วย
"""

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient

from core.app import create_app
from core.config import get_settings
from core.ratelimit import RateLimited, check_rate_limit, reset


@pytest.fixture
def client():
    asyncio.run(reset())
    app = create_app()
    with TestClient(app) as c:
        yield c
    asyncio.run(reset())


@pytest.fixture
def limits(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "login_rate_limit_per_account", 3)
    monkeypatch.setattr(settings, "login_rate_limit_per_ip", 0)  # แยกทดสอบทีละมิติ
    return settings


def _login(client, email="admin@example.com", password="wrong-password"):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def test_failed_logins_get_blocked_after_limit(client, limits):
    for i in range(3):
        assert _login(client).status_code == 401, f"ครั้งที่ {i + 1} ควรเป็น 401"
    r = _login(client)
    assert r.status_code == 429, "เกินโควตาแล้วต้องถูกกัน ไม่ใช่ปล่อยให้เดาต่อ"
    assert int(r.headers["Retry-After"]) > 0


def test_successful_login_is_not_counted(client, limits):
    """ผู้ใช้จริงที่ล็อกอินถูกต้องซ้ำ ๆ ต้องไม่โดนกวน — นับเฉพาะครั้งที่ล้มเหลว"""
    for _ in range(6):
        r = _login(client, password="test-admin-pw-9f3k2x")
        assert r.status_code == 200, r.text


def test_per_ip_limit_covers_many_accounts(client, monkeypatch):
    """ยิงคนละอีเมลทุกครั้งก็ต้องโดนกัน — ไม่งั้น credential stuffing ผ่านฉลุย"""
    settings = get_settings()
    monkeypatch.setattr(settings, "login_rate_limit_per_ip", 4)
    monkeypatch.setattr(settings, "login_rate_limit_per_account", 0)

    codes = [_login(client, email=f"nobody{i}@example.com").status_code for i in range(6)]
    assert 429 in codes, f"ยิงคนละบัญชี 6 ครั้งควรโดนกัน แต่ได้ {codes}"


def test_limit_can_be_disabled(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "login_rate_limit_per_ip", 0)
    monkeypatch.setattr(settings, "login_rate_limit_per_account", 0)
    assert all(_login(client).status_code == 401 for _ in range(8))


def test_check_rate_limit_peek_does_not_count():
    async def scenario():
        await reset()
        for _ in range(3):
            await check_rate_limit("unit:peek", limit=3, window_seconds=60)
        # ใช้โควตาครบแล้ว -> การเช็คแบบไม่นับเพิ่มต้องกันตั้งแต่ก่อนทำงานหนัก
        with pytest.raises(RateLimited):
            await check_rate_limit("unit:peek", 3, 60, increment=False)
        # และยังต่ำกว่าโควตาต้องผ่านโดยไม่นับเพิ่ม
        await reset()
        await check_rate_limit("unit:peek", limit=3, window_seconds=60)
        await check_rate_limit("unit:peek", 3, 60, increment=False)
        await reset()

    asyncio.run(scenario())


def test_warns_when_behind_untrusted_proxy(client, caplog):
    """อยู่หลัง proxy ที่ยังไม่ได้ตั้ง FORWARDED_ALLOW_IPS = ลิมิตต่อ IP กลายเป็นลิมิตรวม

    uvicorn เขียน request.client ใหม่จาก X-Forwarded-For ให้เฉพาะเมื่อ peer อยู่ใน
    FORWARDED_ALLOW_IPS (ค่าเริ่มต้น 127.0.0.1) — deploy ใน Docker หลัง Caddy จะไม่เข้าเงื่อนไข
    ทำให้ทุกคนถูกนับรวมเป็น IP เดียว ตรวจไม่เจอตอนเทสเพราะ TestClient ไม่ได้ผ่าน proxy
    ต้องมี warning ให้ operator เห็นตอนรันจริง
    """
    asyncio.run(reset())
    with caplog.at_level("WARNING"):
        r = client.post(
            "/api/auth/login",
            json={"email": "admin@example.com", "password": "admin"},
            headers={"X-Forwarded-For": "203.0.113.9"},
        )
    assert r.status_code == 200, r.text
    assert any("FORWARDED_ALLOW_IPS" in rec.getMessage() for rec in caplog.records), (
        "มี X-Forwarded-For แต่ client ไม่ตรง — ต้องเตือน operator"
    )


def test_no_warning_when_proxy_is_trusted(client, caplog):
    """ตั้งค่าถูกแล้ว (uvicorn เขียน client ให้ตรงกับ XFF) ต้องไม่รบกวนด้วย warning"""
    asyncio.run(reset())
    with caplog.at_level("WARNING"):
        client.post(
            "/api/auth/login",
            json={"email": "admin@example.com", "password": "admin"},
            headers={"X-Forwarded-For": "testclient"},  # TestClient ใช้ host นี้
        )
    assert not any(
        "FORWARDED_ALLOW_IPS" in rec.getMessage() for rec in caplog.records
    ), "ตั้งค่าถูกแล้วยังเตือนอยู่ — จะกลายเป็น warning ที่คนเลิกอ่าน"


def test_no_warning_without_proxy_header(client, caplog):
    """ไม่ได้อยู่หลัง proxy เลย ก็ต้องไม่เตือน"""
    asyncio.run(reset())
    with caplog.at_level("WARNING"):
        client.post(
            "/api/auth/login",
            json={"email": "admin@example.com", "password": "admin"},
        )
    assert not any("FORWARDED_ALLOW_IPS" in rec.getMessage() for rec in caplog.records)
