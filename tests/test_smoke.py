"""Smoke test — บูตทั้งระบบบน sqlite: loader -> install -> auth -> RBAC -> tools"""

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

os.environ["PSTACK_DATABASE_URL"] = "sqlite+aiosqlite:///./test_pstack.db"
os.environ["PSTACK_SECRET_KEY"] = "test-secret"
os.environ["PSTACK_MODULES"] = "users"

import pytest
from fastapi.testclient import TestClient

from core.app import create_app


@pytest.fixture(scope="module")
def client():
    db_file = pathlib.Path("./test_pstack.db")
    if db_file.exists():
        db_file.unlink()
    app = create_app()
    with TestClient(app) as c:
        yield c
    if db_file.exists():
        db_file.unlink()


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert "users" in r.json()["modules"]


def test_login_and_me(client):
    r = client.post(
        "/api/auth/login", json={"email": "admin@example.com", "password": "admin"}
    )
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]

    r = client.get("/api/users/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["email"] == "admin@example.com"
    assert r.json()["is_superuser"] is True


def test_rbac_and_create_user(client):
    token = client.post(
        "/api/auth/login", json={"email": "admin@example.com", "password": "admin"}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # superuser สร้าง user ใหม่ได้
    r = client.post(
        "/api/users",
        json={"email": "somchai@example.com", "password": "pw1234", "full_name": "สมชาย"},
        headers=headers,
    )
    assert r.status_code == 201, r.text

    # user ใหม่ไม่มี role -> list users ต้องโดน 403
    user_token = client.post(
        "/api/auth/login", json={"email": "somchai@example.com", "password": "pw1234"}
    ).json()["access_token"]
    r = client.get("/api/users", headers={"Authorization": f"Bearer {user_token}"})
    assert r.status_code == 403

    # ไม่มี token -> 401
    assert client.get("/api/users/me").status_code == 401


def test_tool_registry():
    from core.ai import get_tools

    tools = {t.name: t for t in get_tools()}
    assert "count_users" in tools
    assert "search_users" in tools
    schema = tools["search_users"].input_schema
    assert schema["properties"]["query"]["type"] == "string"
    assert "query" in schema["required"]
