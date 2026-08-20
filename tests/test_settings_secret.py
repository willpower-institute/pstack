"""SECRET_KEY ที่เดาได้ = ใครก็ปลอม token เป็น admin ได้ — ระบบต้องไม่ยอมบูต

เทสระดับ unit ไม่บูต app ไม่แตะ DB
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest
from pydantic import ValidationError

from core.config import MIN_SECRET_KEY_LENGTH, WEAK_SECRET_KEYS, Settings

STRONG = "s" * MIN_SECRET_KEY_LENGTH


def _settings(**kwargs) -> Settings:
    # _env_file=None กัน .env ของเครื่อง dev เข้ามาแทรก
    return Settings(_env_file=None, **kwargs)


def test_strong_key_accepted():
    assert _settings(secret_key=STRONG, debug=False).secret_key == STRONG


@pytest.mark.parametrize("weak", sorted(WEAK_SECRET_KEYS))
def test_weak_key_refuses_to_boot(weak):
    with pytest.raises(ValidationError, match="PSTACK_SECRET_KEY"):
        _settings(secret_key=weak, debug=False)


def test_short_key_refuses_to_boot():
    with pytest.raises(ValidationError, match="PSTACK_SECRET_KEY"):
        _settings(secret_key="x" * (MIN_SECRET_KEY_LENGTH - 1), debug=False)


def test_error_message_tells_how_to_fix():
    with pytest.raises(ValidationError) as exc:
        _settings(secret_key="", debug=False)
    assert "PSTACK_SECRET_KEY=" in str(exc.value), "ข้อความ error ต้องบอกวิธีสร้างคีย์ให้ด้วย"


def test_debug_mode_warns_but_still_boots(caplog):
    """dev ยังลองเล่นได้ ไม่ต้องตั้งคีย์ก่อน — แต่ต้องมี warning เตือนไว้"""
    with caplog.at_level("WARNING"):
        assert _settings(secret_key="change-me", debug=True).debug is True
    assert any("PSTACK_SECRET_KEY" in r.getMessage() for r in caplog.records)
