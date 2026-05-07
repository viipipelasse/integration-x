"""SFTP XML parsing and Twenty Company sync orchestration."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import posixpath
import stat
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

import httpx
import paramiko
import polars as pl

from integration_x.config import ConfigError, Settings, load_settings


SOAP_NAMESPACES = {
    "s0": "http://soap-crm.local/types",
}


@dataclass(frozen=True)
class XmlCompany:
    """Internal representation of a company row from the ERP XML file."""

    name: str | None = None
    website: str | None = None
    address: str | None = None
    city: str | None = None
    country: str | None = None


TwentyCompanyPayload = dict[str, Any]


@dataclass(frozen=True)
class SyncSummary:
    files_found: int = 0
    files_processed: int = 0
    rows_created: int = 0
    rows_updated: int = 0
    rows_failed: int = 0
    rows_skipped: int = 0


class RunLog:
    def __init__(self) -> None:
        self._lines: list[str] = []

    def add(self, message: str) -> None:
        line = f"{_utc_timestamp()} {message}"
        self._lines.append(line)
        print(line)

    def text(self) -> str:
        return "\n".join(self._lines) + "\n"


class TwentyClient:
    """Small Twenty REST client for company upserts."""

    def __init__(
        self,
        base_url: str,
        api_token: str,
        *,
        timeout_seconds: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=base_url,
            timeout=timeout_seconds,
            headers={
                "Authorization": f"Bearer {api_token}",
                "Content-Type": "application/json",
            },
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def find_company_by_name(self, name: str) -> dict[str, Any] | None:
        response = self._client.get(
            "/rest/companies",
            params={
                "filter": f"name[eq]:{name}",
                "limit": "1",
            },
        )
        response.raise_for_status()
        companies = _extract_twenty_records(response.json())
        return companies[0] if companies else None

    def create_company(self, payload: TwentyCompanyPayload) -> dict[str, Any]:
        response = self._client.post("/rest/companies", json=payload)
        if _is_duplicate_response(response) and "domainName" in payload:
            response = self._client.post("/rest/companies", json=_without_domain_name(payload))
        response.raise_for_status()
        return response.json()

    def update_company(
        self,
        company_id: str,
        payload: TwentyCompanyPayload,
    ) -> dict[str, Any]:
        response = self._client.patch(f"/rest/companies/{company_id}", json=payload)
        if _is_duplicate_response(response) and "domainName" in payload:
            response = self._client.patch(
                f"/rest/companies/{company_id}",
                json=_without_domain_name(payload),
            )
        response.raise_for_status()
        return response.json()


def parse_companies_xml(xml_content: str | bytes) -> list[XmlCompany]:
    """Parse SOAP XML content into internal company rows.

    Invalid XML is intentionally allowed to raise ``ElementTree.ParseError`` so
    the orchestration layer can leave malformed SFTP files in place for retry.
    """

    root = ET.fromstring(xml_content)
    company_elements = root.findall(".//s0:Company", SOAP_NAMESPACES)

    return [
        XmlCompany(
            name=_element_text(company, "Name"),
            website=_element_text(company, "Website"),
            address=_element_text(company, "Address"),
            city=_element_text(company, "City"),
            country=_element_text(company, "Country"),
        )
        for company in company_elements
    ]


def parse_companies_xml_file(path: str | Path) -> list[XmlCompany]:
    """Read an SFTP-downloaded XML file from disk and parse its company rows."""

    return parse_companies_xml(Path(path).read_bytes())


def normalize_companies(companies: list[XmlCompany]) -> list[XmlCompany]:
    """Trim strings, convert blanks to missing, skip nameless rows, and dedupe."""

    if not companies:
        return []

    frame = pl.DataFrame([asdict(company) for company in companies])
    normalized = frame.with_columns(
        [
            pl.col(column)
            .cast(pl.String)
            .str.strip_chars()
            .replace("", None)
            .alias(column)
            for column in frame.columns
        ]
    )

    return [
        XmlCompany(**row)
        for row in normalized.filter(pl.col("name").is_not_null())
        .unique(subset=["name"], keep="first", maintain_order=True)
        .to_dicts()
    ]


def to_twenty_company_payload(company: XmlCompany) -> TwentyCompanyPayload:
    """Map one normalized internal company row to a Twenty create payload."""

    if not company.name:
        raise ValueError("Twenty Company payload requires a non-empty name")

    payload: TwentyCompanyPayload = {"name": company.name}

    if company.website:
        payload["domainName"] = {
            "primaryLinkUrl": company.website,
            "primaryLinkLabel": "",
            "secondaryLinks": [],
        }

    address = _twenty_address(company)
    if address:
        payload["address"] = address

    return payload


def map_xml_companies_to_twenty_companies(
    companies: list[XmlCompany],
) -> list[TwentyCompanyPayload]:
    """Return normalized Twenty Company payloads without creating CRM objects."""

    return [
        to_twenty_company_payload(company)
        for company in normalize_companies(companies)
    ]


def sync_payloads_to_twenty(
    payloads: list[TwentyCompanyPayload],
    twenty: TwentyClient,
    run_log: RunLog,
) -> SyncSummary:
    """Create or update Twenty Companies, matching existing records by name."""

    summary = SyncSummary()

    for payload in payloads:
        name = str(payload["name"])
        try:
            existing = twenty.find_company_by_name(name)
            if existing:
                company_id = _twenty_record_id(existing)
                if not company_id:
                    raise ValueError(f"Twenty Company {name!r} did not include an id")
                twenty.update_company(company_id, payload)
                run_log.add(f"row updated name={name!r} company_id={company_id!r}")
                summary = _add_to_summary(summary, rows_updated=1)
            else:
                twenty.create_company(payload)
                run_log.add(f"row created name={name!r}")
                summary = _add_to_summary(summary, rows_created=1)
        except Exception as exc:  # noqa: BLE001 - per-row failures must not stop the run
            run_log.add(f"row skipped name={name!r} reason=twenty_error detail={exc}")
            summary = _add_to_summary(summary, rows_failed=1)

    return summary


def run() -> int:
    """Run one SFTP XML to Twenty CRM sync pass."""

    run_log = RunLog()
    sftp: paramiko.SFTPClient | None = None
    transport: paramiko.Transport | None = None
    twenty: TwentyClient | None = None
    log_path: str | None = None

    try:
        settings = load_settings()
        run_log.add("run started")
        log_path = _remote_join(settings.sftp_inbox, "log", f"{_log_filename()}.log")

        transport = paramiko.Transport((settings.sftp_host, settings.sftp_port))
        transport.connect(
            username=settings.sftp_username,
            password=settings.sftp_password,
        )
        sftp = paramiko.SFTPClient.from_transport(transport)
        _ensure_sftp_dir(sftp, _remote_join(settings.sftp_inbox, "processed"))
        _ensure_sftp_dir(sftp, _remote_join(settings.sftp_inbox, "log"))

        twenty = TwentyClient(
            settings.twenty_base_url,
            settings.twenty_api_token,
            timeout_seconds=settings.timeout_seconds,
        )
        summary = run_sync(settings, sftp, twenty, run_log)
        run_log.add(
            "run summary "
            f"files_found={summary.files_found} "
            f"files_processed={summary.files_processed} "
            f"rows_created={summary.rows_created} "
            f"rows_updated={summary.rows_updated} "
            f"rows_failed={summary.rows_failed} "
            f"rows_skipped={summary.rows_skipped}"
        )
        return 0
    except (ConfigError, ET.ParseError, OSError, paramiko.SSHException, httpx.HTTPError) as exc:
        run_log.add(f"run failed reason={exc}")
        return 1
    except Exception as exc:  # noqa: BLE001 - CLI should return documented failure code
        run_log.add(f"run failed reason={exc}")
        return 1
    finally:
        if sftp and log_path:
            try:
                _write_sftp_text(sftp, log_path, run_log.text())
            except Exception as exc:  # noqa: BLE001 - log upload is best-effort after failures
                print(f"{_utc_timestamp()} run log upload failed reason={exc}")
        if twenty:
            twenty.close()
        if sftp:
            sftp.close()
        if transport:
            transport.close()


def run_sync(
    settings: Settings,
    sftp: paramiko.SFTPClient,
    twenty: TwentyClient,
    run_log: RunLog,
) -> SyncSummary:
    xml_files = _list_inbox_xml_files(sftp, settings.sftp_inbox)
    summary = SyncSummary(files_found=len(xml_files))

    for remote_path in xml_files:
        run_log.add(f"file found path={remote_path!r}")
        xml_content = _read_sftp_bytes(sftp, remote_path)
        companies = parse_companies_xml(xml_content)
        payloads = map_xml_companies_to_twenty_companies(companies)
        skipped_rows = len(companies) - len(payloads)
        run_log.add(
            f"file parsed path={remote_path!r} rows={len(companies)} "
            f"normalized_rows={len(payloads)} skipped_rows={skipped_rows}"
        )

        file_summary = sync_payloads_to_twenty(payloads, twenty, run_log)
        processed_path = _processed_path(sftp, settings.sftp_inbox, remote_path)
        sftp.rename(remote_path, processed_path)
        run_log.add(f"file archived from={remote_path!r} to={processed_path!r}")
        summary = _add_to_summary(
            summary,
            files_processed=1,
            rows_created=file_summary.rows_created,
            rows_updated=file_summary.rows_updated,
            rows_failed=file_summary.rows_failed,
            rows_skipped=skipped_rows,
        )

    return summary


def _element_text(company: ET.Element, local_name: str) -> str | None:
    return company.findtext(f"s0:{local_name}", namespaces=SOAP_NAMESPACES)


def _twenty_address(company: XmlCompany) -> dict[str, str]:
    address: dict[str, str] = {}

    if company.address:
        address["addressStreet1"] = company.address
    if company.city:
        address["addressCity"] = company.city
    if company.country:
        address["addressCountry"] = company.country

    return address


def _extract_twenty_records(data: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(data.get("data"), list):
        return data["data"]
    if isinstance(data.get("data"), dict) and isinstance(data["data"].get("companies"), list):
        return data["data"]["companies"]
    if isinstance(data.get("companies"), list):
        return data["companies"]
    return []


def _twenty_record_id(record: dict[str, Any]) -> str | None:
    value = record.get("id")
    return str(value) if value else None


def _is_duplicate_response(response: httpx.Response) -> bool:
    if response.status_code != 400:
        return False
    try:
        messages = response.json().get("messages", [])
    except ValueError:
        return False
    return any("duplicate entry" in str(message).lower() for message in messages)


def _without_domain_name(payload: TwentyCompanyPayload) -> TwentyCompanyPayload:
    return {key: value for key, value in payload.items() if key != "domainName"}


def _list_inbox_xml_files(sftp: paramiko.SFTPClient, inbox: str) -> list[str]:
    paths: list[str] = []
    for item in sftp.listdir_attr(inbox):
        if not item.filename.endswith(".xml"):
            continue
        if not stat.S_ISREG(item.st_mode):
            continue
        paths.append(_remote_join(inbox, item.filename))
    return sorted(paths)


def _read_sftp_bytes(sftp: paramiko.SFTPClient, remote_path: str) -> bytes:
    with sftp.open(remote_path, "rb") as remote_file:
        return remote_file.read()


def _write_sftp_text(sftp: paramiko.SFTPClient, remote_path: str, text: str) -> None:
    with sftp.open(remote_path, "w") as remote_file:
        remote_file.write(text)


def _ensure_sftp_dir(sftp: paramiko.SFTPClient, remote_path: str) -> None:
    try:
        sftp.stat(remote_path)
    except OSError:
        sftp.mkdir(remote_path)


def _processed_path(
    sftp: paramiko.SFTPClient,
    inbox: str,
    remote_path: str,
) -> str:
    filename = posixpath.basename(remote_path)
    candidate = _remote_join(inbox, "processed", filename)
    try:
        sftp.stat(candidate)
    except OSError:
        return candidate

    stem, suffix = posixpath.splitext(filename)
    return _remote_join(inbox, "processed", f"{stem}-{_log_filename()}{suffix}")


def _remote_join(*parts: str) -> str:
    return posixpath.join(*(part.strip("/") for part in parts if part))


def _utc_timestamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log_filename() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _add_to_summary(summary: SyncSummary, **changes: int) -> SyncSummary:
    values = asdict(summary)
    for key, value in changes.items():
        values[key] += value
    return SyncSummary(**values)
