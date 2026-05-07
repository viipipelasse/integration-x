"""Environment-backed runtime configuration."""

from __future__ import annotations

from dataclasses import dataclass
import os
from urllib.parse import urlparse

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    sftp_host: str
    sftp_port: int
    sftp_username: str
    sftp_password: str
    sftp_inbox: str
    twenty_base_url: str
    twenty_api_token: str
    timeout_seconds: float = 30.0


class ConfigError(ValueError):
    """Raised when required runtime configuration is missing or invalid."""


def load_settings() -> Settings:
    """Load settings from environment, allowing a local .env fallback."""

    load_dotenv(override=False)

    missing = [
        name
        for name in (
            "SFTP_HOST",
            "SFTP_PORT",
            "SFTP_USERNAME",
            "SFTP_PASSWORD",
            "SFTP_INBOX",
            "TWENTY_BASE_URL",
            "TWENTY_API_TOKEN",
        )
        if not os.getenv(name)
    ]
    if missing:
        raise ConfigError(f"Missing required environment variables: {', '.join(missing)}")

    try:
        sftp_port = int(os.environ["SFTP_PORT"])
    except ValueError as exc:
        raise ConfigError("SFTP_PORT must be an integer") from exc

    try:
        timeout_seconds = float(os.getenv("INTEGRATION_X_TIMEOUT_SECONDS", "30"))
    except ValueError as exc:
        raise ConfigError("INTEGRATION_X_TIMEOUT_SECONDS must be a number") from exc

    return Settings(
        sftp_host=os.environ["SFTP_HOST"],
        sftp_port=sftp_port,
        sftp_username=os.environ["SFTP_USERNAME"],
        sftp_password=os.environ["SFTP_PASSWORD"],
        sftp_inbox=os.environ["SFTP_INBOX"].rstrip("/") or ".",
        twenty_base_url=_normalize_base_url(os.environ["TWENTY_BASE_URL"]),
        twenty_api_token=os.environ["TWENTY_API_TOKEN"],
        timeout_seconds=timeout_seconds,
    )


def _normalize_base_url(value: str) -> str:
    base_url = value.strip().rstrip("/")
    if not base_url:
        raise ConfigError("TWENTY_BASE_URL must not be empty")
    if not urlparse(base_url).scheme:
        base_url = f"https://{base_url}"
    return base_url
