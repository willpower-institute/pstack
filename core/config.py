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

# รหัส admin คนแรก — ค่าที่เดาได้ทันทีหรือเคยเป็น default
WEAK_ADMIN_PASSWORDS = frozenset(
    {
        "",
        "admin",
        "admin123",
        "password",
        "passw0rd",
        "123456",
        "12345678",
        "changeme",
        "change-me",
        "pstack",
        "secret",
    }
)
MIN_ADMIN_PASSWORD_LENGTH = 12


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

    # กันเดารหัสผ่าน — ตั้ง 0 เพื่อปิด (ไม่แนะนำบนเครื่องที่เปิดสาธารณะ)
    login_rate_limit_per_ip: int = 20          # ต่อ 1 นาที
    login_rate_limit_per_account: int = 5      # ต่อ 5 นาที ต่อหนึ่งอีเมล
    # เปิด /docs /redoc /openapi.json หรือไม่ — None = ตามค่า debug
    # (เปิดสาธารณะ = เปิดเผยผังทุก endpoint ทุก schema ให้คนนอกอ่าน)
    expose_docs: bool | None = None
    admin_email: str = "admin@example.com"
    # ไม่มี default ที่ใช้งานได้ — ใช้ตอนสร้าง admin คนแรกเท่านั้น
    admin_password: str = ""

    def _reject_weak(
        self, value: str, env_name: str, weak: frozenset[str], min_length: int, why: str
    ) -> None:
        """ปฏิเสธการบูตถ้าค่าอ่อนแอ — debug=true เตือนแต่ยังรันต่อได้ (dev)"""
        if value not in weak and len(value) >= min_length:
            return

        reason = (
            "ยังไม่ได้ตั้ง"
            if value == ""
            else "เป็นค่าที่เดาได้ทันที"
            if value in weak
            else f"สั้นเกินไป ({len(value)} ตัวอักษร)"
        )
        message = (
            f"{env_name} {reason} — {why}\n"
            f"ตั้งเป็นค่าสุ่มยาวอย่างน้อย {min_length} ตัวอักษร เช่น:\n"
            f"  {env_name}={secrets.token_urlsafe(max(min_length, 24))}"
        )
        if self.debug:
            logger.warning("%s", message)
            return
        raise ValueError(message)

    @model_validator(mode="after")
    def _validate_credentials(self) -> "Settings":
        self._reject_weak(
            self.secret_key,
            "PSTACK_SECRET_KEY",
            WEAK_SECRET_KEYS,
            MIN_SECRET_KEY_LENGTH,
            "JWT ทั้งระบบเซ็นด้วยคีย์นี้ ถ้าเดาได้ ใครก็ปลอม token เป็น admin ได้ทันที",
        )
        self._reject_weak(
            self.admin_password,
            "PSTACK_ADMIN_PASSWORD",
            WEAK_ADMIN_PASSWORDS,
            MIN_ADMIN_PASSWORD_LENGTH,
            "ใช้สร้างบัญชี superuser คนแรก ถ้าเดาได้ก็เข้าระบบได้เลยโดยไม่ต้องหาช่องโหว่อะไร",
        )
        return self

    @property
    def docs_enabled(self) -> bool:
        return self.debug if self.expose_docs is None else self.expose_docs

    @property
    def modules_list(self) -> list[str]:
        return [m.strip() for m in self.modules.split(",") if m.strip()]

    @property
    def addons_paths_list(self) -> list[str]:
        return [p.strip() for p in self.addons_paths.split(",") if p.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
