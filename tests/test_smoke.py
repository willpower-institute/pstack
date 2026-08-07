"""Smoke test — บูตทั้งระบบบน sqlite: loader -> install -> auth -> RBAC -> tools"""

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

os.environ["PSTACK_DATABASE_URL"] = "sqlite+aiosqlite:///./test_pstack.db"
os.environ["PSTACK_SECRET_KEY"] = "test-secret"
os.environ["PSTACK_MODULES"] = "users,storage,ai_agent"
os.environ["PSTACK_STORAGE_DIR"] = "./test_uploads"

import pytest
from fastapi.testclient import TestClient

from core.app import create_app


@pytest.fixture(scope="module")
def client():
    import shutil

    db_file = pathlib.Path("./test_pstack.db")
    uploads = pathlib.Path("./test_uploads")
    if db_file.exists():
        db_file.unlink()
    if uploads.exists():
        shutil.rmtree(uploads)
    app = create_app()
    with TestClient(app) as c:
        yield c
    if db_file.exists():
        db_file.unlink()
    if uploads.exists():
        shutil.rmtree(uploads)


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


def test_storage_flow(client):
    token = client.post(
        "/api/auth/login", json={"email": "admin@example.com", "password": "admin"}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # upload
    r = client.post(
        "/api/storage/upload",
        files={"file": ("hello.txt", b"pstack file content", "text/plain")},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    file_id = r.json()["id"]
    assert r.json()["original_name"] == "hello.txt"

    # list
    r = client.get("/api/storage", headers=headers)
    assert any(f["id"] == file_id for f in r.json())

    # download — เนื้อไฟล์ต้องตรง
    r = client.get(f"/api/storage/{file_id}/download", headers=headers)
    assert r.status_code == 200
    assert r.content == b"pstack file content"

    # คนอื่น (non-superuser) เข้าถึงไฟล์เราไม่ได้
    other_token = client.post(
        "/api/auth/login", json={"email": "somchai@example.com", "password": "pw1234"}
    ).json()["access_token"]
    r = client.get(
        f"/api/storage/{file_id}/download",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert r.status_code == 403

    # delete
    r = client.delete(f"/api/storage/{file_id}", headers=headers)
    assert r.status_code == 204
    r = client.get(f"/api/storage/{file_id}/download", headers=headers)
    assert r.status_code == 404


class FakeStream:
    """แทน anthropic streaming context — script การตอบของโมเดลทีละ turn"""

    def __init__(self, deltas, final):
        self._deltas = deltas
        self._final = final

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    @property
    def text_stream(self):
        async def gen():
            for d in self._deltas:
                yield d

        return gen()

    async def get_final_message(self):
        return self._final


def test_agent_session_and_tools(client):
    token = client.post(
        "/api/auth/login", json={"email": "admin@example.com", "password": "admin"}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    r = client.post("/api/agent/sessions", json={"title": ""}, headers=headers)
    assert r.status_code == 201
    assert client.get("/api/agent/sessions", headers=headers).json()

    # superuser เห็น tools ของโมดูล users
    tools = client.get("/api/agent/tools", headers=headers).json()
    names = {t["name"] for t in tools}
    assert {"count_users", "search_users"} <= names


def test_agent_chat_with_tool(client, monkeypatch):
    from types import SimpleNamespace

    from addons.ai_agent.runtime import AgentRuntime

    # turn 1: โมเดลขอเรียก count_users, turn 2: ตอบ text จบ
    turns = [
        FakeStream(
            [],
            SimpleNamespace(
                content=[
                    {"type": "tool_use", "id": "tu_1", "name": "count_users", "input": {}}
                ],
                stop_reason="tool_use",
            ),
        ),
        FakeStream(
            ["มีผู้ใช้ ", "2 คนครับ"],
            SimpleNamespace(
                content=[{"type": "text", "text": "มีผู้ใช้ 2 คนครับ"}],
                stop_reason="end_turn",
            ),
        ),
    ]
    monkeypatch.setattr(
        AgentRuntime, "_stream_ctx", lambda self, *, system, messages, tools: turns.pop(0)
    )

    token = client.post(
        "/api/auth/login", json={"email": "admin@example.com", "password": "admin"}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    sid = client.post("/api/agent/sessions", json={}, headers=headers).json()["id"]
    r = client.post(
        f"/api/agent/sessions/{sid}/messages",
        json={"text": "ตอนนี้มีผู้ใช้กี่คน"},
        headers=headers,
    )
    assert r.status_code == 200
    body = r.text
    assert '"tool_use"' in body and '"count_users"' in body   # เรียก tool จริง
    assert '"tool_result"' in body and '"ok": true' in body   # tool รันสำเร็จ
    assert '"done"' in body

    # ประวัติถูกเก็บ: ข้อความ user + คำตอบ assistant (แถว tool ไม่โชว์)
    msgs = client.get(f"/api/agent/sessions/{sid}/messages", headers=headers).json()
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["text"] == "มีผู้ใช้ 2 คนครับ"

    # session title ถูกตั้งจากข้อความแรก
    sessions = client.get("/api/agent/sessions", headers=headers).json()
    assert any(s["title"] == "ตอนนี้มีผู้ใช้กี่คน" for s in sessions)


def test_event_bus_local():
    import asyncio

    from core.events import EventBus

    bus = EventBus()
    received = []

    @bus.on("test.event")
    async def handler(payload):
        received.append(payload)

    asyncio.run(bus.emit("test.event", {"x": 1}))
    assert received == [{"x": 1}]


def test_tool_registry():
    from core.ai import get_tools

    tools = {t.name: t for t in get_tools()}
    assert "count_users" in tools
    assert "search_users" in tools
    schema = tools["search_users"].input_schema
    assert schema["properties"]["query"]["type"] == "string"
    assert "query" in schema["required"]
