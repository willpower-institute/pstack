"""ด่านพื้นฐานที่ควรมีติดตัวมาเลย — security header, ปิด /docs, ไม่รั่ว error ภายใน"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient

from core.app import create_app
from core.config import get_settings


@pytest.fixture
def app_client():
    """ไม่ใช้ context manager — ไม่ต้องรัน lifespan สำหรับหน้าที่ไม่แตะ DB"""

    def build() -> TestClient:
        return TestClient(create_app())

    return build


# เขียนค่าที่คาดหวังไว้ตรงนี้ ไม่ import จากโค้ด — จะได้จับได้ถ้ามีใครลบทิ้ง
EXPECTED_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


def test_security_headers_on_every_response(app_client):
    r = app_client().get("/healthz")
    for name, value in EXPECTED_HEADERS.items():
        assert r.headers.get(name) == value, f"ขาด header {name}"


def test_docs_hidden_by_default_when_not_debug(app_client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "debug", False)
    monkeypatch.setattr(settings, "expose_docs", None)

    client = app_client()
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404, f"{path} ไม่ควรเปิดให้คนนอกเห็น"


def test_docs_can_be_turned_on_explicitly(app_client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "debug", False)
    monkeypatch.setattr(settings, "expose_docs", True)

    client = app_client()
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_docs_follow_debug_flag(app_client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "expose_docs", None)
    monkeypatch.setattr(settings, "debug", True)
    assert app_client().get("/docs").status_code == 200

