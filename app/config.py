from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    tg_bot_token: str
    tg_chat_id: int
    tg_webhook_secret: str
    tg_polling: bool = True
    claude_bin: str = "claude"
    db_url: str = "postgresql://stock:stock@db:5432/stock_dashboard"
    data_dir: Path = Path("./data")
    seed_path: Path = Path("./seed/initial_holdings.yaml")
    host: str = "0.0.0.0"
    port: int = 8080
    tz: str = "Asia/Seoul"


@lru_cache
def get_settings() -> Settings:
    return Settings()
