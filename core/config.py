import logging
import secrets
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# ค่าที่เคยเป็น default / อยู่ใน .env.example / เดาได้ทันที — ห้ามใช้จริงเด็ดขาด
WEAK_SECRET_KEYS = frozenset(
    {
        "",
        "change-me",
        "change-me-to-a-long-random-string",
        "changeme",
        "secret",
        "test-secret",
    }
)
MIN_SECRET_KEY_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PSTACK_", env_file=".env", extra="ignore")

    app_name: str = "pstack"
    debug: bool = False
    # ไม่มี default ที่ใช้งานได้ — ต้องตั้งเองเสมอ (ดู _validate_secret_key)
    secret_key: str = ""

    database_url: str = "postgresql+asyncpg://pstack:pstack@localhost:5432/pstack"
    redis_url: str = "redis://localhost:6379/0"

    # โมดูลที่ต้องการให้ติดตั้ง/โหลด (comma-separated) — kernel resolve dependency ให้เอง
    modules: str = "users"
    addons_paths: str = "addons"

    access_token_expire_minutes: int = 60 * 24
    admin_email: str = "admin@example.com"
    admin_password: str = "admin"

    @model_validator(mode="after")
    def _validate_secret_key(self) -> "Settings":
        """ปฏิเสธการบูตถ้า secret key อ่อนแอ — JWT ทั้งระบบเซ็นด้วยคีย์นี้

        คีย์ที่เดาได้ = ใครก็ปลอม token เป็น user id ไหนก็ได้ รวมถึง superuser
        โดยไม่ต้องรู้รหัสผ่านอะไรเลย ต่อให้ตั้งรหัส admin ไว้แน่นหนาแค่ไหน
        """
        key = self.secret_key
        if key not in WEAK_SECRET_KEYS and len(key) >= MIN_SECRET_KEY_LENGTH:
            return self

        reason = (
            "ยังไม่ได้ตั้ง"
            if key == ""
            else "เป็นค่าตัวอย่างที่เผยแพร่อยู่แล้ว"
            if key in WEAK_SECRET_KEYS
            else f"สั้นเกินไป ({len(key)} ตัวอักษร)"
        )
        message = (
            f"PSTACK_SECRET_KEY {reason} — JWT ทั้งระบบเซ็นด้วยคีย์นี้ "
            f"ถ้าเดาได้ ใครก็ปลอม token เป็น admin ได้ทันที\n"
            f"ตั้งเป็นค่าสุ่มยาวอย่างน้อย {MIN_SECRET_KEY_LENGTH} ตัวอักษร เช่น:\n"
            f"  PSTACK_SECRET_KEY={secrets.token_urlsafe(48)}"
        )
        if self.debug:
            # dev/เทส: เตือนแต่ยังรันต่อได้ จะได้ไม่ขวางการลองเล่น
            logger.warning("%s", message)
            return self
        raise ValueError(message)

    @property
    def modules_list(self) -> list[str]:
        return [m.strip() for m in self.modules.split(",") if m.strip()]

    @property
    def addons_paths_list(self) -> list[str]:
        return [p.strip() for p in self.addons_paths.split(",") if p.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
