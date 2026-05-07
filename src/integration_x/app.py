"""XML parsing and Twenty Company payload mapping."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

import polars as pl


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
    """Return Twenty Company creation payloads without creating CRM objects."""

    return [
        to_twenty_company_payload(company)
        for company in normalize_companies(companies)
    ]


def run() -> int:
    """Placeholder command entry point for future SFTP orchestration."""
    return 0


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
