"""Scaffold checks for future normalization tests."""

from pathlib import Path
import xml.etree.ElementTree as ET

from integration_x.app import (
    XmlCompany,
    map_xml_companies_to_twenty_companies,
    parse_companies_xml_file,
)
from integration_x.config import _normalize_base_url


def test_normalize_base_url_adds_https_to_bare_host() -> None:
    assert _normalize_base_url("crm.example.com/") == "https://crm.example.com"
    assert _normalize_base_url("https://crm.example.com/") == "https://crm.example.com"


def test_customer_fixture_matches_soap_company_shape() -> None:
    fixture = Path(__file__).parent / "fixtures" / "Customers.xml"

    root = ET.parse(fixture).getroot()

    namespaces = {"s0": "http://soap-crm.local/types"}
    companies = root.findall(".//s0:Company", namespaces)
    assert len(companies) == 1
    assert companies[0].findtext("s0:Name", namespaces=namespaces) == "Acme AB"


def test_parse_customer_fixture_to_internal_schema() -> None:
    fixture = Path(__file__).parent / "fixtures" / "Customers.xml"

    companies = parse_companies_xml_file(fixture)

    assert companies == [
        XmlCompany(
            name="Acme AB",
            website="https://acme.example",
            address="Main Street 1",
            city="Stockholm",
            country="Sweden",
        )
    ]


def test_fixture_maps_to_twenty_company_creation_payload() -> None:
    fixture = Path(__file__).parent / "fixtures" / "Customers.xml"

    payloads = map_xml_companies_to_twenty_companies(
        parse_companies_xml_file(fixture)
    )

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
        }
    ]
