"""Scaffold checks for the application entry points."""

from __future__ import annotations

from dataclasses import dataclass
import io
import stat

from integration_x import __version__
from integration_x.config import Settings
from integration_x.app import (
    RunLog,
    SyncSummary,
    TwentyClient,
    XmlCompany,
    map_xml_companies_to_twenty_companies,
    run,
    run_sync,
    sync_payloads_to_twenty,
)


def test_package_exposes_version() -> None:
    assert __version__ == "0.1.0"


def test_run_reports_configuration_failure(monkeypatch) -> None:
    monkeypatch.setattr("integration_x.config.load_dotenv", lambda override=False: None)
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

    assert run() == 1


def test_maps_normalized_companies_to_twenty_payloads() -> None:
    companies = [
        XmlCompany(
            name="  Acme AB  ",
            website=" https://acme.example ",
            address=" Main Street 1 ",
            city=" Stockholm ",
            country=" Sweden ",
        ),
        XmlCompany(name="Acme AB", website="https://duplicate.example"),
        XmlCompany(name="   "),
        XmlCompany(name=None, website="https://missing-name.example"),
        XmlCompany(name="Minimal AB", website="", address="", city="", country=""),
    ]

    payloads = map_xml_companies_to_twenty_companies(companies)

    assert payloads == [
        {
            "name": "Acme AB",
            "domainName": {
                "primaryLinkUrl": "https://acme.example",
                "primaryLinkLabel": "",
                "secondaryLinks": [],
            },
            "address": {
                "addressStreet1": "Main Street 1",
                "addressCity": "Stockholm",
                "addressCountry": "Sweden",
            },
        },
        {"name": "Minimal AB"},
    ]


def test_mapping_skips_all_nameless_rows() -> None:
    payloads = map_xml_companies_to_twenty_companies(
        [
            XmlCompany(),
            XmlCompany(name=" "),
        ]
    )

    assert payloads == []


def test_sync_payloads_updates_existing_company_by_name() -> None:
    run_log = RunLog()
    twenty = FakeTwentyClient(existing={"Acme AB": {"id": "company-1", "name": "Acme AB"}})

    summary = sync_payloads_to_twenty(
        [{"name": "Acme AB"}, {"name": "New AB"}],
        twenty,
        run_log,
    )

    assert summary == SyncSummary(rows_created=1, rows_updated=1)
    assert twenty.updated == [("company-1", {"name": "Acme AB"})]
    assert twenty.created == [{"name": "New AB"}]


def test_run_sync_reads_sftp_xml_upserts_and_archives_processed_file() -> None:
    settings = Settings(
        sftp_host="sftp.example",
        sftp_port=22,
        sftp_username="user",
        sftp_password="secret",
        sftp_inbox="ERPOut",
        twenty_base_url="https://twenty.example",
        twenty_api_token="token",
    )
    sftp = FakeSftp(
        files={
            "ERPOut/Customers.xml": (
                b"""<?xml version="1.0" encoding="UTF-8"?>
<soap11env:Envelope xmlns:soap11env="http://schemas.xmlsoap.org/soap/envelope/"
                    xmlns:tns="http://soap-crm.local/services"
                    xmlns:s0="http://soap-crm.local/types">
  <soap11env:Body>
    <tns:GetCompaniesResponse>
      <s0:Company><s0:Name>Acme AB</s0:Name></s0:Company>
      <s0:Company><s0:Name>New AB</s0:Name></s0:Company>
    </tns:GetCompaniesResponse>
  </soap11env:Body>
</soap11env:Envelope>"""
            )
        }
    )
    twenty = FakeTwentyClient(existing={"Acme AB": {"id": "company-1", "name": "Acme AB"}})
    run_log = RunLog()

    summary = run_sync(settings, sftp, twenty, run_log)

    assert summary == SyncSummary(
        files_found=1,
        files_processed=1,
        rows_created=1,
        rows_updated=1,
    )
    assert "ERPOut/Customers.xml" not in sftp.files
    assert "ERPOut/processed/Customers.xml" in sftp.files
    assert twenty.updated == [("company-1", {"name": "Acme AB"})]
    assert twenty.created == [{"name": "New AB"}]


@dataclass
class FakeSftpAttrs:
    filename: str
    st_mode: int = stat.S_IFREG | 0o644


class FakeSftp:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = dict(files)
        self.directories = {"ERPOut", "ERPOut/processed", "ERPOut/log"}

    def listdir_attr(self, path: str) -> list[FakeSftpAttrs]:
        prefix = f"{path}/"
        attrs: list[FakeSftpAttrs] = []
        for file_path in self.files:
            if not file_path.startswith(prefix):
                continue
            filename = file_path.removeprefix(prefix)
            if "/" not in filename:
                attrs.append(FakeSftpAttrs(filename=filename))
        return attrs

    def open(self, path: str, mode: str) -> io.BytesIO | io.StringIO:
        if "r" in mode:
            return io.BytesIO(self.files[path])
        return io.StringIO()

    def rename(self, source: str, target: str) -> None:
        self.files[target] = self.files.pop(source)

    def stat(self, path: str) -> object:
        if path in self.files or path in self.directories:
            return object()
        raise OSError(path)

    def mkdir(self, path: str) -> None:
        self.directories.add(path)


class FakeTwentyClient(TwentyClient):
    def __init__(self, existing: dict[str, dict[str, str]] | None = None) -> None:
        self.existing = existing or {}
        self.created: list[dict[str, object]] = []
        self.updated: list[tuple[str, dict[str, object]]] = []

    def find_company_by_name(self, name: str) -> dict[str, str] | None:
        return self.existing.get(name)

    def create_company(self, payload: dict[str, object]) -> dict[str, object]:
        self.created.append(payload)
        return {"data": payload}

    def update_company(
        self,
        company_id: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        self.updated.append((company_id, payload))
        return {"data": payload}
