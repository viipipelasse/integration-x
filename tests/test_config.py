"""Configuration loading tests."""

from __future__ import annotations

import pytest

from integration_x.config import ConfigError, load_settings


def test_load_settings_reads_required_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        "SFTP_HOST": "sftp.example.test",
        "SFTP_PORT": "2022",
        "SFTP_USERNAME": "viipipe",
        "SFTP_PASSWORD": "secret",
        "SFTP_INBOX": "ERPOut",
        "TWENTY_BASE_URL": "https://crm.example.test",
        "TWENTY_API_TOKEN": "token",
        "INTEGRATION_X_TIMEOUT_SECONDS": "12.5",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    settings = load_settings()

    assert settings.sftp_host == "sftp.example.test"
    assert settings.sftp_port == 2022
    assert settings.sftp_inbox == "ERPOut"
    assert settings.timeout_seconds == 12.5


def test_load_settings_reads_dotenv_without_dependency(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    for name in (
        "SFTP_HOST",
        "SFTP_PORT",
        "SFTP_USERNAME",
        "SFTP_PASSWORD",
        "SFTP_INBOX",
        "TWENTY_BASE_URL",
        "TWENTY_API_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    tmp_path.joinpath(".env").write_text(
        "\n".join(
            (
                "SFTP_HOST=sftp.example.test",
                "SFTP_PORT=2022",
                "SFTP_USERNAME=viipipe",
                "SFTP_PASSWORD='secret'",
                "SFTP_INBOX=ERPOut",
                "TWENTY_BASE_URL=https://crm.example.test",
                'TWENTY_API_TOKEN="token"',
            )
        ),
        encoding="utf-8",
    )

    settings = load_settings()

    assert settings.sftp_host == "sftp.example.test"
    assert settings.sftp_password == "secret"
    assert settings.twenty_api_token == "token"


def test_load_settings_reports_missing_required_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    for name in (
        "SFTP_HOST",
        "SFTP_PORT",
        "SFTP_USERNAME",
        "SFTP_PASSWORD",
        "SFTP_INBOX",
        "TWENTY_BASE_URL",
        "TWENTY_API_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ConfigError, match="Missing required environment variables"):
        load_settings()
