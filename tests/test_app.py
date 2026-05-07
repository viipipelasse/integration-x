"""Scaffold checks for the application entry points."""

from integration_x import __version__
from integration_x.app import run


def test_package_exposes_version() -> None:
    assert __version__ == "0.1.0"


def test_placeholder_run_exits_successfully() -> None:
    assert run() == 0
