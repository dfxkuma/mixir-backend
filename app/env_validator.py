from typing import Literal
from functools import lru_cache
from pydantic import field_validator

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    APP_ENV: Literal["development", "production", "testing"]
    JWT_SECRET_KEY: str
    SERVER_PORT: int
    MONGODB_URI: str
    MONGODB_DATABASE: str

    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str
    GOOGLE_REDIRECT_URI: str

    GMAIL_ADDRESS: str
    GMAIL_PASSWORD: str
    SHEET_TEMPLATE_ID: str

    ADMIN_EMAIL_HOST: str

    @staticmethod
    @field_validator("SERVER_PORT")
    def check_port_range(value: int):
        if not 0 < value < 65536:
            raise ValueError("SERVER_PORT number must be between 1 and 65535")
        return value


@lru_cache()
def get_settings() -> Settings:
    return Settings()
