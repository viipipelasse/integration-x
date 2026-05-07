"""Scaffold checks for future normalization tests."""

from pathlib import Path
import xml.etree.ElementTree as ET


def test_customer_fixture_matches_soap_company_shape() -> None:
    fixture = Path(__file__).parent / "fixtures" / "Customers.xml"

    root = ET.parse(fixture).getroot()

    namespaces = {"s0": "http://soap-crm.local/types"}
    companies = root.findall(".//s0:Company", namespaces)
    assert len(companies) == 1
    assert companies[0].findtext("s0:Name", namespaces=namespaces) == "Acme AB"
