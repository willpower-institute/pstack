"""LINE Messaging API client (httpx) + signature verify + message builders"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging

import httpx

logger = logging.getLogger(__name__)

API_BASE = "https://api.line.me/v2/bot"


def verify_signature(channel_secret: str, body: bytes, signature: str | None) -> bool:
    mac = hmac.new(channel_secret.encode(), body, hashlib.sha256)
    expected = base64.b64encode(mac.digest()).decode()
    return hmac.compare_digest(expected, signature or "")


def text_message(text: str, quick_menu: list[dict] | None = None) -> dict:
    msg: dict = {"type": "text", "text": text[:5000]}
    if quick_menu:
        msg["quickReply"] = {
            "items": [
                {
                    "type": "action",
                    "action": {"type": "uri", "label": item["label"][:20], "uri": item["url"]},
                }
                for item in quick_menu[:13]
            ]
        }
    return msg


async def _post(access_token: str, path: str, payload: dict) -> bool:
    async with httpx.AsyncClient(timeout=10) as http:
        r = await http.post(
            f"{API_BASE}{path}",
            json=payload,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if r.status_code >= 400:
        logger.error("LINE API %s -> %s %s", path, r.status_code, r.text[:300])
        return False
    return True


async def reply(access_token: str, reply_token: str, messages: list[dict]) -> bool:
    return await _post(
        access_token, "/message/reply", {"replyToken": reply_token, "messages": messages}
    )


async def push(access_token: str, to: str, messages: list[dict]) -> bool:
    return await _post(access_token, "/message/push", {"to": to, "messages": messages})


async def multicast(access_token: str, to: list[str], messages: list[dict]) -> bool:
    ok = True
    for i in range(0, len(to), 500):  # LINE จำกัด 500 ids ต่อครั้ง
        ok = (
            await _post(
                access_token,
                "/message/multicast",
                {"to": to[i : i + 500], "messages": messages},
            )
            and ok
        )
    return ok
