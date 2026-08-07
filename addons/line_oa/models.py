from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class LineChannel(Base):
    """หนึ่ง LINE OA — deploy เดียวรับได้หลาย channel (แยกด้วย channel_id ใน webhook URL)"""

    __tablename__ = "line_channels"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    channel_id: Mapped[str] = mapped_column(String(64), unique=True)  # LINE channel ID
    channel_secret: Mapped[str] = mapped_column(String(128))
    access_token: Mapped[str] = mapped_column(Text)
    agent_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    greeting: Mapped[str] = mapped_column(Text, default="")
    # เมนู quick reply เป็น data: [{"label": "...", "url": "..."}] — url ใช้ LIFF URL ได้เลย
    quick_menu: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class LineUser(Base):
    """คนที่ทักเข้ามาใน OA — ผูกกับ pstack user ได้ผ่าน link code"""

    __tablename__ = "line_users"
    __table_args__ = (UniqueConstraint("channel_pk", "line_user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_pk: Mapped[int] = mapped_column(
        ForeignKey("line_channels.id", ondelete="CASCADE"), index=True
    )
    line_user_id: Mapped[str] = mapped_column(String(64), index=True)
    display_name: Mapped[str] = mapped_column(String(255), default="")
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    agent_session_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_sessions.id", ondelete="SET NULL"), nullable=True
    )
    followed: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class LineLinkCode(Base):
    """โค้ดผูกบัญชี — user ขอโค้ดจากระบบ แล้วพิมพ์ `link <code>` ในแชท LINE"""

    __tablename__ = "line_link_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(8), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
