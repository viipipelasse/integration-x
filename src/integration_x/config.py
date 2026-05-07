"""Environment-backed configuration for Integration-X."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv(override: bool = False) -> bool:
        loaded = False
        env_path = Path(".env")
        if not env_path.is_file():
            return loaded

        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            name, value = line.split("=", 1)
            name = name.strip()
            if not name or (not override and name in os.environ):
                continue

            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]

            os.environ[name] = value
            loaded = True

        return loaded


class ConfigError(ValueError):
    """Raised when required runtime configuration is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    sftp_host: str
    sftp_port: int
    sftp_username: str
    sftp_password: str
    sftp_inbox: str
    twenty_base_url: str
    twenty_api_token: str
    timeout_seconds: float = 30


REQUIRED_ENV = (
    "SFTP_HOST",
    "SFTP_PORT",
    "SFTP_USERNAME",
    "SFTP_PASSWORD",
    "SFTP_INBOX",
    "TWENTY_BASE_URL",
    "TWENTY_API_TOKEN",
)


def load_settings() -> Settings:
    """Load `.env` plus real environment variables into validated settings."""

    load_dotenv(override=False)

    missing = [name for name in REQUIRED_ENV if not os.getenv(name)]
    if missing:
        raise ConfigError(
            "Missing required environment variables: " + ", ".join(sorted(missing))
        )

    try:
        sftp_port = int(os.environ["SFTP_PORT"])
    except ValueError as exc:
        raise ConfigError("SFTP_PORT must be an integer") from exc

    try:
        timeout_seconds = float(os.getenv("INTEGRATION_X_TIMEOUT_SECONDS", "30"))
    except ValueError as exc:
        raise ConfigError("INTEGRATION_X_TIMEOUT_SECONDS must be a number") from exc

    if sftp_port <= 0:
        raise ConfigError("SFTP_PORT must be greater than 0")
    if timeout_seconds <= 0:
        raise ConfigError("INTEGRATION_X_TIMEOUT_SECONDS must be greater than 0")

    return Settings(
        sftp_host=os.environ["SFTP_HOST"],
        sftp_port=sftp_port,
        sftp_username=os.environ["SFTP_USERNAME"],
        sftp_password=os.environ["SFTP_PASSWORD"],
        sftp_inbox=os.environ["SFTP_INBOX"].strip("/"),
        twenty_base_url=os.environ["TWENTY_BASE_URL"],
        twenty_api_token=os.environ["TWENTY_API_TOKEN"],
        timeout_seconds=timeout_seconds,
    )
