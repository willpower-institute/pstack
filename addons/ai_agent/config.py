from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class AISettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PSTACK_AI_", env_file=".env", extra="ignore")

    model: str = "claude-opus-5"
    max_tokens: int = 16000
    max_loops: int = 10  # จำนวนรอบ tool-use สูงสุดต่อหนึ่งข้อความ
    # server-side refusal fallbacks (แนะนำเปิดไว้สำหรับ claude-opus-5)
    fallbacks: bool = True
    # ข้อความเสริมต่อท้าย system prompt (บริบทเฉพาะระบบของคุณ)
    system_extra: str = ""


@lru_cache
def get_ai_settings() -> AISettings:
    return AISettings()
