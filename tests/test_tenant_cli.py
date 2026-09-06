"""tenant-aware CLI — `python cli.py tenancy ...` (module CLI extension point)

boot ครั้งเดียวให้ lifespan สร้างตาราง tenancy บน sqlite ของเทส แล้วยิงคำสั่งผ่าน CliRunner
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from core.app import create_app


@pytest.fixture(scope="module")
def booted():
    with TestClient(create_app()):  # lifespan → sync_modules → สร้างตาราง tenancy
        pass
    yield


@pytest.fixture
def run(booted):
    from cli import app

    runner = CliRunner()

    def _invoke(*args):
        return runner.invoke(app, ["tenancy", *args])

    return _invoke


def test_tenancy_group_is_mounted(run):
    r = run("--help")
    assert r.exit_code == 0
    assert "create" in r.stdout and "add-member" in r.stdout and "members" in r.stdout


def test_create_and_list(run):
    r = run("create", "cli-co", "--name", "CLI Co")
    assert r.exit_code == 0 and "cli-co" in r.stdout
    assert "cli-co" in run("list").stdout

    r = run("create", "cli-co")  # ซ้ำ
    assert r.exit_code == 1 and "มีอยู่แล้ว" in r.stdout

    r = run("create", "Bad Id")  # id ผิดรูปแบบ
    assert r.exit_code == 1


def test_add_member_and_members(run):
    run("create", "cli-clinic")
    r = run("add-member", "cli-clinic", "admin@example.com", "--role", "owner")
    assert r.exit_code == 0 and "admin@example.com" in r.stdout

    members = run("members", "cli-clinic").stdout
    assert "admin@example.com" in members and "owner" in members

    assert run("add-member", "cli-clinic", "admin@example.com").exit_code == 1  # ซ้ำ
    assert run("add-member", "nope", "admin@example.com").exit_code == 1  # ไม่มี tenant
    assert run("add-member", "cli-clinic", "ghost@example.com").exit_code == 1  # ไม่มี user
