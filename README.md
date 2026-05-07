# Integration-X

Integration-X is a small Python CLI for importing customer XML files from SFTP
into Twenty CRM Companies.

The implementation contract is documented in [SPEC.md](SPEC.md). This
It loads SFTP and Twenty credentials from environment variables, processes
`*.xml` files in the configured SFTP inbox, creates or updates Twenty Companies
matched by exact trimmed name, archives handled files under `processed/`, and
writes a run log under `log/`.

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
