from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://localhost/floluo"
    app_origin: str = "https://erp.local"
    secure_cookies: bool = True
    session_minutes: int = 30
