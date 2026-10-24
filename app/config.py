from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str
    forum_chat_id: int
    solo_dsn: str = ""
    db_path: str = "data/support.db"

    ticket_start: int = 0
    auto_close_hours: int = 48
    reopen_hours: int = 72
    spam_limit: int = 8
    spam_window: int = 60
    ask_rating: bool = True
