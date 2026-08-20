"""verify_signature ต้องไม่ raise ไม่ว่าผู้เรียกจะส่งอะไรมาใน header

เทสระดับ unit — ไม่บูต app ไม่แตะ DB
"""

import base64
import hashlib
import hmac
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from addons.line_oa.client import verify_signature

SECRET = "testsecret"
BODY = b'{"events":[]}'


def _valid_signature(secret: str = SECRET, body: bytes = BODY) -> str:
    mac = hmac.new(secret.encode(), body, hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()


def test_valid_signature_passes():
    assert verify_signature(SECRET, BODY, _valid_signature()) is True


def test_wrong_signature_rejected():
    assert verify_signature(SECRET, BODY, "wrongbutbase64==") is False


def test_missing_signature_rejected():
    assert verify_signature(SECRET, BODY, None) is False


def test_non_ascii_signature_rejected_not_raised():
    """เดิม hmac.compare_digest() กับ str non-ASCII จะ raise TypeError
    ทำให้ POST /api/line/webhook/{id} ตอบ 500 แทน 400 (ผู้โจมตียิงซ้ำ ๆ ได้)"""
    assert verify_signature(SECRET, BODY, "ปลอม") is False
    assert verify_signature(SECRET, BODY, "🙃") is False
