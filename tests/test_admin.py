"""Admin UI (server-rendered, cookie session) — โมดูล admin

ครอบ: ต้องล็อกอินก่อนเข้า, cookie session, สร้าง user/role, assign role แล้วได้สิทธิ์จริง,
รหัสผิด/ผู้ใช้ไม่มีสิทธิ์ถูกกัน, ปิดบัญชีตัวเองไม่ได้, tenant + member, หน้าโมดูล
"""

import asyncio
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest
from conftest import ADMIN_PASSWORD
from fastapi.testclient import TestClient

from core.app import create_app
from core.ratelimit import reset


@pytest.fixture
def client():
    asyncio.run(reset())
    app = create_app()
    with TestClient(app) as c:
        yield c
    asyncio.run(reset())


def _login(client, email="admin@example.com", password=ADMIN_PASSWORD):
    """ล็อกอินผ่านฟอร์ม → cookie ถูกเก็บใน client jar (ตาม redirect ไป /admin)"""
    return client.post("/admin/login", data={"email": email, "password": password})


def _bearer(client, email="admin@example.com", password=ADMIN_PASSWORD):
    token = client.post(
        "/api/auth/login", json={"email": email, "password": password}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_login_required_redirects(client):
    r = client.get("/admin", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/admin/login"


def test_login_and_dashboard(client):
    assert _login(client).status_code == 200
    body = client.get("/admin").text
    assert "แดชบอร์ด" in body and "โมดูล" in body


def test_wrong_password_rejected(client):
    r = client.post(
        "/admin/login", data={"email": "admin@example.com", "password": "definitely-wrong"}
    )
    assert r.status_code == 200 and "ไม่ถูกต้อง" in r.text  # re-render login พร้อม error
    assert client.get("/admin", follow_redirects=False).status_code == 303  # ไม่มี cookie


def test_create_user_and_role(client):
    _login(client)
    r = client.post(
        "/admin/users",
        data={"email": "u1@example.com", "password": "userpass123", "full_name": "หนึ่ง"},
    )
    assert r.status_code == 200 and "u1@example.com" in client.get("/admin/users").text

    # flash อยู่ใน query ของ redirect target (PRG) — เช็คจาก response ที่ follow redirect มาแล้ว
    r = client.post("/admin/users", data={"email": "u1@example.com", "password": "userpass123"})
    assert "มีอยู่แล้ว" in r.text  # อีเมลซ้ำ

    r = client.post("/admin/users", data={"email": "u2@example.com", "password": "short"})
    assert "อย่างน้อย" in r.text  # รหัสสั้น

    client.post("/admin/roles", data={"name": "editor", "permissions": "faq.manage users.read"})
    page = client.get("/admin/roles").text
    assert "editor" in page and "faq.manage" in page


def test_assign_role_grants_admin_access(client):
    """assign role ที่มี admin.access ให้ user ธรรมดา → user นั้นเข้า admin ได้จริง (RBAC ครบวง)"""
    _login(client)
    client.post("/admin/roles", data={"name": "sysadmin", "permissions": "admin.access"})
    client.post("/admin/users", data={"email": "op@example.com", "password": "userpass123"})

    uid = next(
        u["id"]
        for u in client.get("/api/users", headers=_bearer(client)).json()
        if u["email"] == "op@example.com"
    )
    # ดึง role_id ของ sysadmin จาก checkbox ในหน้า users
    m = re.search(r'name="role_ids" value="(\d+)"[^>]*>\s*sysadmin', client.get("/admin/users").text)
    assert m, "ควรมี checkbox ของ role sysadmin ในหน้า users"
    client.post(f"/admin/users/{uid}/roles", data={"role_ids": m.group(1)})

    # op เป็น user ธรรมดา แต่ตอนนี้มี admin.access → เข้า admin ได้
    op = TestClient(create_app())
    assert op.post("/admin/login", data={"email": "op@example.com", "password": "userpass123"}).status_code == 200
    assert op.get("/admin", follow_redirects=False).status_code == 200


def test_non_admin_user_blocked(client):
    _login(client)
    client.post("/admin/users", data={"email": "plain@example.com", "password": "userpass123"})
    client.cookies.clear()  # ออกจาก admin
    # ผู้ใช้ธรรมดา (ไม่ใช่ superuser, ไม่มี admin.access) ล็อกอิน admin ไม่ได้
    r = client.post("/admin/login", data={"email": "plain@example.com", "password": "userpass123"})
    assert r.status_code == 200 and "สิทธิ์" in r.text
    assert client.get("/admin", follow_redirects=False).status_code == 303


def test_cannot_disable_self(client):
    _login(client)
    me = client.get("/api/users/me", headers=_bearer(client)).json()
    r = client.post(f"/admin/users/{me['id']}/toggle")
    assert "ตัวเอง" in r.text  # flash จาก redirect target


def test_tenant_create_and_member(client):
    _login(client)
    r = client.post(
        "/admin/tenants", data={"tenant_id": "admin-clinic", "display_name": "คลินิกทดสอบ"}
    )
    assert r.status_code == 200 and "admin-clinic" in client.get("/admin/tenants").text

    client.post("/admin/tenants/admin-clinic/members", data={"user_id": 1, "role": "owner"})
    assert "owner" in client.get("/admin/tenants").text  # member row แสดง role


def test_modules_page_lists_modules(client):
    _login(client)
    body = client.get("/admin/modules").text
    assert "admin" in body and "users" in body and "tenancy" in body
