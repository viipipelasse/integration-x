"""Scaffold checks for the application entry points."""

from integration_x import __version__
from integration_x.app import (
    XmlCompany,
    map_xml_companies_to_twenty_companies,
    run,
)


def test_package_exposes_version() -> None:
    assert __version__ == "0.1.0"


def test_placeholder_run_exits_successfully() -> None:
    assert run() == 0


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
