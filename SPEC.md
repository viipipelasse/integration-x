# Integration-X Specification

Status: Draft v1

Purpose: one small Python CLI that reads customer XML files from SFTP and
creates missing Companies in Twenty CRM.

## 1. Scope

Integration-X runs once, then exits. A scheduler such as cron or systemd is
responsible for calling it.

It must:

- List `*.xml` files in a configured SFTP inbox.
- Parse SOAP XML customer records.
- Normalize records with Polars.
- Create a Twenty Company when no Company with the same trimmed `name` exists.
- Skip existing Companies and bad rows.
- Move successfully handled files to `processed/`.
- Write a simple run log to stdout and SFTP `log/`.

It must not:

- Sync from Twenty back to the ERP.
- Update existing Companies.
- Create other Twenty objects.
- Run as a daemon, web app, dashboard, or API.
- Promise exactly-once delivery.

## 2. Source XML

Each SFTP inbox file is a SOAP XML document containing zero or more
`s0:Company` elements.

Namespaces:

| Prefix | URI |
|--------|-----|
| `soap11env` | `http://schemas.xmlsoap.org/soap/envelope/` |
| `tns` | `http://soap-crm.local/services` |
| `s0` | `http://soap-crm.local/types` |

Customer fields:

| XML element | Required | Use |
|-------------|----------|-----|
| `Name` | yes | Twenty `name`, dedup key |
| `Website` | no | Twenty `domainName.primaryLinkUrl` |
| `Address` | no | Twenty `address.addressStreet1` |
| `City` | no | Twenty `address.addressCity` |
| `Country` | no | Twenty `address.addressCountry` |

Other XML fields may be ignored for v1.

Rows without a non-empty `Name` are skipped and logged.

## 3. Twenty Mapping

Before sending to Twenty:

- Trim all string values.
- Convert empty strings to missing values.
- Drop duplicate names within the same file, keeping the first row.
- Omit optional fields when their source value is missing.

Request body examples:

```json
{ "name": "Acme AB" }
```

```json
{
  "name": "Acme AB",
  "domainName": {
    "primaryLinkUrl": "https://acme.example",
    "primaryLinkLabel": "",
    "secondaryLinks": []
  },
  "address": {
    "addressStreet1": "Main Street 1",
    "addressCity": "Stockholm",
    "addressCountry": "Sweden"
  }
}
```

For each normalized row:

1. Query Twenty for an active Company with the same exact `name`.
2. If found, log it as skipped.
3. If not found, create it.

Existing Companies are never updated in v1.

## 4. SFTP Layout

One configured directory is used as the inbox:

```text
<SFTP_INBOX>/
├── *.xml
├── processed/
└── log/
```

Rules:

- Only regular `*.xml` files directly inside the inbox are processed.
- `processed/` and `log/` are created if missing.
- A file is moved to `processed/` only after it has been parsed and its rows
  have been attempted.
- Malformed or unreadable XML stays in the inbox for investigation/retry.
- If a processed filename already exists, append a UTC timestamp before `.xml`.

## 5. Configuration

Configuration comes from environment variables. A local `.env` file may be
loaded for development, but real environment variables win over `.env` values.

Required:

| Variable | Example |
|----------|---------|
| `SFTP_HOST` | `192.168.1.98` |
| `SFTP_PORT` | `2022` |
| `SFTP_USERNAME` | `viipipe` |
| `SFTP_PASSWORD` | secret |
| `SFTP_INBOX` | `ERPOut` |
| `TWENTY_BASE_URL` | `https://crm.example.com` |
| `TWENTY_API_TOKEN` | secret |

Optional:

| Variable | Default |
|----------|---------|
| `INTEGRATION_X_TIMEOUT_SECONDS` | `30` |

Secrets must never be logged.

## 6. Logging and Exit Codes

Log one plain-text line per important event:

- run started
- file found
- file parsed
- row created
- row skipped with reason
- file archived
- run summary
- run failed

Write the same log to stdout and `<SFTP_INBOX>/log/<UTC timestamp>.log`.

Exit codes:

- `0`: run completed; per-row skips are allowed.
- `1`: configuration, SFTP connection, file parse, archive, log upload, or
  unexpected fatal error occurred.

Per-row Twenty API failures are logged and skipped so one bad row does not
stop the rest of the file.

## 7. Minimal Project Layout

Keep the implementation small. Do not split every concern into its own file
until the code actually needs it.

```text
integration-x/
├── README.md
├── SPEC.md
├── .env.example
├── .gitignore
├── pyproject.toml
├── src/
│   └── integration_x/
│       ├── __init__.py
│       ├── __main__.py      # allows: python -m integration_x
│       ├── config.py        # env/.env loading and validation
│       └── app.py           # SFTP, XML parse, normalize, Twenty calls, run()
└── tests/
    ├── fixtures/
    │   └── Customers.xml
    ├── test_normalize.py
    └── test_app.py
```

`app.py` can be split later only when there is a clear reason. For v1, keeping
SFTP, parsing, mapping, and orchestration together is simpler and easier to
follow than a directory full of thin wrappers.

## 8. Dependencies

Use the smallest practical dependency set:

- `polars`
- `paramiko`
- `httpx`
- `python-dotenv`

Use Python's standard `xml.etree.ElementTree` unless it proves insufficient.

Python version: 3.11+.

## 9. Future Work

Out of scope for v1:

- Mapping `OrgNumber`, `Industry`, `Phone`, or `Email`.
- Storing ERP `Id` in Twenty.
- Deduplicating by ERP `Id`.
- Updating existing Companies.
- Creating People.
- Deleting or soft-deleting Companies.
- Concurrent runs against the same inbox.
