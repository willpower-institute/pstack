from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class LineSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PSTACK_LINE_", env_file=".env", extra="ignore")

    # true = ประมวลผล webhook แบบ await ก่อนตอบ 200 (ใช้ในเทส) — ปกติ false เพื่อตอบ LINE เร็ว
    sync_mode: bool = False
    link_code_ttl_minutes: int = 10


@lru_cache
def get_line_settings() -> LineSettings:
    return LineSettings()
