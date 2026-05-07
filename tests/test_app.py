"""Application entry point and SFTP layout checks."""

from __future__ import annotations

import stat
from contextlib import contextmanager
from dataclasses import dataclass

from integration_x import __version__
from integration_x.app import setup_sftp_layout, validate_sftp_layout
from integration_x.config import Settings


def test_package_exposes_version() -> None:
    assert __version__ == "0.1.0"


@dataclass
class FakeAttrs:
    st_mode: int


class FakeSFTP:
    def __init__(self, paths: dict[str, int]) -> None:
        self.paths = paths
        self.created: list[str] = []

    def stat(self, path: str) -> FakeAttrs:
        if path not in self.paths:
            raise FileNotFoundError(path)
        return FakeAttrs(self.paths[path])

    def mkdir(self, path: str) -> None:
        self.created.append(path)
        self.paths[path] = stat.S_IFDIR | 0o755

    def close(self) -> None:
        pass


def settings() -> Settings:
    return Settings(
        sftp_host="sftp.example.test",
        sftp_port=2022,
        sftp_username="viipipe",
        sftp_password="secret",
        sftp_inbox="ERPOut",
        twenty_base_url="https://crm.example.test",
        twenty_api_token="token",
    )


def test_setup_sftp_layout_validates_customers_xml_and_creates_folders() -> None:
    sftp = FakeSFTP(
        {
            "ERPOut": stat.S_IFDIR | 0o755,
            "ERPOut/Customers.xml": stat.S_IFREG | 0o644,
        }
    )

    @contextmanager
    def connector(_: Settings):
        yield sftp

    setup_sftp_layout(settings(), connector)

    assert sftp.created == ["ERPOut/processed", "ERPOut/log"]


def test_validate_sftp_layout_fails_when_customers_xml_is_missing() -> None:
    sftp = FakeSFTP({"ERPOut": stat.S_IFDIR | 0o755})

    try:
        validate_sftp_layout(sftp, "ERPOut")
    except FileNotFoundError as exc:
        assert str(exc) == "ERPOut/Customers.xml"
    else:
        raise AssertionError("Expected missing Customers.xml to fail validation")


def test_validate_sftp_layout_is_idempotent_for_existing_folders() -> None:
    sftp = FakeSFTP(
        {
            "ERPOut": stat.S_IFDIR | 0o755,
            "ERPOut/Customers.xml": stat.S_IFREG | 0o644,
            "ERPOut/processed": stat.S_IFDIR | 0o755,
            "ERPOut/log": stat.S_IFDIR | 0o755,
        }
    )

    validate_sftp_layout(sftp, "ERPOut")

    assert sftp.created == []
