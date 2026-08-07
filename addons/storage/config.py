"""ตัวอย่าง module-scoped settings — env prefix ของโมดูลเอง ไม่ปนกับ kernel"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class StorageSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PSTACK_STORAGE_", env_file=".env", extra="ignore"
    )

    dir: str = "uploads"  # PSTACK_STORAGE_DIR
    max_size_mb: int = 25  # PSTACK_STORAGE_MAX_SIZE_MB


@lru_cache
def get_storage_settings() -> StorageSettings:
    return StorageSettings()
