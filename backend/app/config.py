from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://cerbos:cerbos@localhost:5432/cerbos"
    cerbos_url: str = "http://localhost:3592"
    litellm_url: str = "http://localhost:4000"
    litellm_master_key: str = ""
    encryption_key: str = ""
    session_secret: str = ""
    demo_mode: bool = False
    cookie_secure: bool = False
    mock_provider_key: str = ""
    allowed_origin: str = "http://localhost:5173"
    # Live policy files: the directory Cerbos watches. Locally this is the repo copy.
    policies_dir: str = str(Path(__file__).resolve().parents[2] / "cerbos" / "policies")
    # The policies this build shipped with: the baseline for diffs and reset.
    shipped_policies_dir: str = str(Path(__file__).resolve().parents[2] / "cerbos" / "policies")


@lru_cache
def settings() -> Settings:
    return Settings()
