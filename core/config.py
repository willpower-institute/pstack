from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PSTACK_", env_file=".env", extra="ignore")

    app_name: str = "pstack"
    debug: bool = False
    secret_key: str = "change-me"

    database_url: str = "postgresql+asyncpg://pstack:pstack@localhost:5432/pstack"
    redis_url: str = "redis://localhost:6379/0"

    # โมดูลที่ต้องการให้ติดตั้ง/โหลด (comma-separated) — kernel resolve dependency ให้เอง
    modules: str = "users"
    addons_paths: str = "addons"

    access_token_expire_minutes: int = 60 * 24

    # เปิด /docs /redoc /openapi.json หรือไม่ — None = ตามค่า debug
    # (เปิดสาธารณะ = เปิดเผยผังทุก endpoint ทุก schema ให้คนนอกอ่าน)
    expose_docs: bool | None = None
    admin_email: str = "admin@example.com"
    admin_password: str = "admin"

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
