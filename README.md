# Integration-X

Integration-X is a small Python CLI scaffold for importing customer XML files
from SFTP into Twenty CRM Companies.

The implementation contract is documented in [SPEC.md](SPEC.md). This
repository currently contains the project layout, packaging metadata, source
package placeholders, test placeholders, and a sample SOAP fixture for the
future implementation pass.

## Layout

```text
integration-x/
├── pyproject.toml
├── src/integration_x/
│   ├── __init__.py
│   ├── __main__.py
│   ├── config.py
│   └── app.py
└── tests/
    ├── fixtures/Customers.xml
    ├── test_normalize.py
    └── test_app.py
```

## Development

Use Python 3.11 or newer.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
pytest
```
