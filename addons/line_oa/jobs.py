"""Background jobs ของ line_oa — ตัวอย่าง broadcast ผ่าน ARQ worker"""

import logging

from sqlalchemy import select

from core.db import get_sessionmaker
from core.jobs import background_job

from addons.line_oa import client as line_client
from addons.line_oa.models import LineChannel, LineUser

logger = logging.getLogger(__name__)


@background_job
async def line_broadcast(ctx: dict, channel_pk: int, text: str) -> str:
    """ส่งข้อความหา follower ทุกคนของ channel (ใช้: await enqueue("line_broadcast", pk, text))"""
    async with get_sessionmaker()() as db:
        channel = await db.get(LineChannel, channel_pk)
        if channel is None:
            return "channel not found"
        result = await db.execute(
            select(LineUser.line_user_id).where(
                LineUser.channel_pk == channel_pk, LineUser.followed.is_(True)
            )
        )
        ids = [row[0] for row in result]
    if not ids:
        return "no followers"
    ok = await line_client.multicast(
        channel.access_token, ids, [line_client.text_message(text)]
    )
    logger.info("line_broadcast -> %d users, ok=%s", len(ids), ok)
    return f"sent to {len(ids)} users"
