"""Integration orchestration and SFTP layout setup."""

from __future__ import annotations

import posixpath
import stat
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Protocol

from integration_x.config import ConfigError, Settings, load_settings

try:
    import paramiko
except ModuleNotFoundError:
    paramiko = None

SFTP_CONNECTION_ERRORS = (OSError,)
if paramiko is not None:
    SFTP_CONNECTION_ERRORS = (OSError, paramiko.SSHException)
RUN_ERRORS = (ConfigError, RuntimeError) + SFTP_CONNECTION_ERRORS


class SFTPClient(Protocol):
    def close(self) -> None: ...

    def mkdir(self, path: str) -> None: ...

    def stat(self, path: str) -> object: ...


SFTP_REQUIRED_DIRECTORIES = ("processed", "log")
CUSTOMERS_XML = "Customers.xml"


def _remote_join(*parts: str) -> str:
    return posixpath.join(*(part.strip("/") for part in parts if part))


def _is_directory(attrs: object) -> bool:
    mode = getattr(attrs, "st_mode", None)
    return mode is not None and stat.S_ISDIR(mode)


def _is_regular_file(attrs: object) -> bool:
    mode = getattr(attrs, "st_mode", None)
    return mode is not None and stat.S_ISREG(mode)


def _ensure_directory(sftp: SFTPClient, path: str) -> None:
    try:
        attrs = sftp.stat(path)
    except FileNotFoundError:
        sftp.mkdir(path)
        return

    if not _is_directory(attrs):
        raise RuntimeError(f"Remote path exists but is not a directory: {path}")


def validate_sftp_layout(sftp: SFTPClient, inbox: str) -> None:
    """Validate ERPOut/Customers.xml and create required inbox folders."""

    inbox_attrs = sftp.stat(inbox)
    if not _is_directory(inbox_attrs):
        raise RuntimeError(f"SFTP inbox is not a directory: {inbox}")

    customers_xml = _remote_join(inbox, CUSTOMERS_XML)
    customers_attrs = sftp.stat(customers_xml)
    if not _is_regular_file(customers_attrs):
        raise RuntimeError(f"Required SFTP file is not a regular file: {customers_xml}")

    for directory in SFTP_REQUIRED_DIRECTORIES:
        _ensure_directory(sftp, _remote_join(inbox, directory))


@contextmanager
def connect_sftp(settings: Settings) -> Iterator[SFTPClient]:
    """Open an SFTP connection using validated environment settings."""

    if paramiko is None:
        raise RuntimeError("paramiko is required for SFTP connections")

    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=settings.sftp_host,
        port=settings.sftp_port,
        username=settings.sftp_username,
        password=settings.sftp_password,
        timeout=settings.timeout_seconds,
        banner_timeout=settings.timeout_seconds,
        auth_timeout=settings.timeout_seconds,
    )

    sftp = client.open_sftp()
    try:
        yield sftp
    finally:
        sftp.close()
        client.close()


def setup_sftp_layout(
    settings: Settings,
    connector: Callable[[Settings], object] = connect_sftp,
) -> None:
    """Connect to SFTP, validate Customers.xml, and create layout folders."""

    with connector(settings) as sftp:
        validate_sftp_layout(sftp, settings.sftp_inbox)


def run() -> int:
    """CLI entry point."""

    try:
        settings = load_settings()
        setup_sftp_layout(settings)
    except RUN_ERRORS as exc:
        print(f"run failed: {exc}", file=sys.stderr)
        return 1

    print("SFTP connection validated and folder structure is ready.")
    return 0
