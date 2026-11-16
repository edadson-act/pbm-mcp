"""Process settings. Secrets and base URLs come from the environment."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

class ConfigError(ValueError):
    """Raised when auth settings are present but cannot be used."""


AuthMode = Literal[
    "none",
    "api-key",
    "bearer-env",
    "forward",
    "client-credentials",
]

AUTH_MODES: frozenset[str] = frozenset(
    {"none", "api-key", "bearer-env", "forward", "client-credentials"}
)


def domain_env_name(domain_id: str, suffix: str) -> str:
    """Environment variable for one API, e.g. PBM_CLAIM_HISTORY_BASE_URL."""
    return f"PBM_{domain_id.upper().replace('-', '_')}_{suffix}"


def domain_env(domain_id: str, suffix: str) -> str | None:
    value = os.environ.get(domain_env_name(domain_id, suffix))
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


class Settings(BaseSettings):
    """Global defaults. Each API can override auth mode and base URL."""

    model_config = SettingsConfigDict(
        env_prefix="PBM_",
        env_file=".env",
        extra="ignore",
    )

    auth_mode: AuthMode = "none"
    api_key: str = ""
    api_key_header: str = "x-api-key"
    bearer_token: str = ""
    token_url: str = ""
    client_id: str = ""
    client_secret: str = ""
    host: str = "127.0.0.1"
    port: int = 8000
    timeout_seconds: float = 30.0
    specs_dir: Path = Path("specs")
    allowlists_dir: Path = Path("allowlists")

    def base_url_for(self, domain_id: str) -> str | None:
        return domain_env(domain_id, "BASE_URL")

    def auth_mode_for(self, domain_id: str) -> AuthMode:
        override = domain_env(domain_id, "AUTH_MODE")
        if override is None:
            return self.auth_mode
        if override not in AUTH_MODES:
            raise ConfigError(
                f"Unknown auth mode {override!r} for {domain_id}. "
                f"Expected one of: {', '.join(sorted(AUTH_MODES))}."
            )
        return override  # type: ignore[return-value]

    def api_key_for(self, domain_id: str) -> str:
        return domain_env(domain_id, "API_KEY") or self.api_key

    def api_key_header_for(self, domain_id: str) -> str:
        return domain_env(domain_id, "API_KEY_HEADER") or self.api_key_header

    def bearer_token_for(self, domain_id: str) -> str:
        return domain_env(domain_id, "BEARER_TOKEN") or self.bearer_token


def get_settings() -> Settings:
    """Load ``.env`` without overriding variables already set in the process."""
    load_dotenv(override=False)
    return Settings()
