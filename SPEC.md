# Integration-X Specification

Status: Draft v1

Purpose: Define a one-shot Python integration that reads Customer records from
an SFTP drop folder and upserts them as Companies in a Twenty CRM workspace.

## 1. Problem Statement

An upstream ERP system drops SOAP-formatted XML files into an SFTP folder.
Customer records in those files must end up as Companies in a Twenty CRM
workspace. Today this is done by hand.

Integration-X automates one direction of that flow:

- Pull new XML files from a known SFTP folder.
- Parse each file into a normalized table using Polars.
- For each row, ensure a matching Company exists in Twenty (no duplicates).
- Move processed files into a `processed/` subfolder on the SFTP server.
- Log per-run results into a `log/` subfolder on the SFTP server.

The integration runs as a single CLI invocation. An external scheduler (cron,
systemd timer, or another job runner) is responsible for running it on a
cadence; Integration-X itself does not loop.

## 2. Goals and Non-Goals

### 2.1 Goals

- Parse SOAP XML drops with the schema documented in `docs/company.soap.xml`.
- Normalize parsed records via a Polars DataFrame so transformations are
  declarative and reusable.
- Upsert into Twenty using only the fields the source can populate cleanly:
  `name`, `domainName`, `address` (street, city, country).
- Skip creation when a Company with the same `name` already exists in Twenty.
- Move each successfully processed file out of the inbox into `processed/`.
- Continue past per-row failures (skip + log), so one bad record cannot stop
  an entire batch.
- Stay runnable on a single Ubuntu host (the developer's WSL instance during
  development) with only Python and a Polars install.

### 2.2 Non-Goals

- Bidirectional sync (Twenty → ERP).
- Updating fields on an existing Company. A name match is treated as
  already-present and is left untouched.
- Other Twenty objects (People, Opportunities, Notes, etc.). Companies only.
- A long-running daemon, polling loop, or in-process scheduler. The CLI runs
  once and exits.
- A web UI, dashboard, or REST API of its own.
- Strong delivery guarantees beyond "at-least-once with name-based dedup."

## 3. System Overview

### 3.1 Components

1. **Config Loader**
   - Reads required configuration from environment variables.
   - Fails fast on missing or malformed values before any I/O.

2. **SFTP Client**
   - Connects to the configured SFTP host with username + password.
   - Lists candidate files under the inbox folder.
   - Downloads each file to a local working directory.
   - Moves successfully processed files into `processed/`.
   - Uploads the run log into `log/`.

3. **SOAP Parser**
   - Parses one XML file into an in-memory list of customer records.
   - Tolerant of missing optional elements; required fields cause the row to
     be skipped with a logged reason.

4. **Polars Normalizer**
   - Converts parsed rows into a Polars DataFrame with a fixed schema.
   - Trims whitespace, normalizes empty strings to nulls, lowercases URLs.
   - Drops rows missing required fields (`name`).
   - De-duplicates within a single batch on a normalized `name` key, keeping
     the first occurrence.

5. **Twenty Client**
   - Wraps the Twenty REST API with bearer-token auth.
   - Looks up an existing Company by exact name match.
   - Creates a Company when none exists.
   - Surfaces HTTP and validation errors to the orchestrator.

6. **Orchestrator (CLI entry point)**
   - Drives the end-to-end flow for a single run: list → download → parse →
     normalize → upsert → archive → log.
   - Owns the run log buffer and exit code.

### 3.2 External Dependencies

- SFTP server reachable at the configured host/port.
- Twenty CRM workspace reachable at the configured base URL.
- Python 3.11+ runtime.
- Python packages: `polars`, `paramiko` (or `asyncssh`), `httpx` (or
  `requests`), `lxml` (or stdlib `xml.etree.ElementTree`),
  `python-dotenv` for `.env` loading.

The exact library choices are implementation-defined; the spec only requires
that the chosen libraries support SFTP with password auth, HTTPS with custom
headers, and namespaced XML parsing.

## 4. Source Data Model

The reference file is `docs/company.soap.xml`. Each file in the SFTP inbox
follows the same shape. Filenames observed so far: `Customers.xml`. The
integration MUST NOT assume a single filename — any `*.xml` file in the
inbox is a candidate.

Envelope:

- Root: `soap11env:Envelope`
- Body: `soap11env:Body`
- Operation response: `tns:ListCompaniesResponse` →
  `tns:ListCompaniesResult`
- Each customer: zero or more `s0:Company` children.

Namespaces:

- `soap11env`: `http://schemas.xmlsoap.org/soap/envelope/`
- `tns`:       `http://soap-crm.local/services`
- `s0`:        `http://soap-crm.local/types`

Customer record fields (all under the `s0` namespace):

| XML element  | Type   | Required | Notes                                 |
|--------------|--------|----------|---------------------------------------|
| `Id`         | int    | yes      | ERP-side identifier. Not mapped yet.  |
| `Name`       | string | yes      | Used as the Twenty dedup key.         |
| `OrgNumber`  | string | no       | Not mapped yet.                       |
| `Industry`   | string | no       | Not mapped yet.                       |
| `Website`    | string | no       | Mapped to `domainName.primaryLinkUrl`.|
| `Phone`      | string | no       | Not mapped yet.                       |
| `Email`      | string | no       | Not mapped yet.                       |
| `Address`    | string | no       | Mapped to `address.addressStreet1`.   |
| `City`       | string | no       | Mapped to `address.addressCity`.      |
| `Country`    | string | no       | Mapped to `address.addressCountry`.   |

Rows missing `Name` are skipped and logged. Unmapped fields are read into the
DataFrame anyway (as columns) so future mappings can be added without
revisiting the parser.

## 5. Target Data Model

Twenty CRM `Company` object, accessed via `POST /rest/companies` and
`GET /rest/companies?filter=...`. Authentication is a bearer token in the
`Authorization` header. See `.agents/skills/twenty-crm/SKILL.md` for full
endpoint reference.

Fields used:

| Twenty field                     | Type              |
|----------------------------------|-------------------|
| `name`                           | string            |
| `domainName.primaryLinkLabel`    | string (empty OK) |
| `domainName.primaryLinkUrl`      | string (URL)      |
| `domainName.secondaryLinks`      | array (empty)     |
| `address.addressStreet1`         | string            |
| `address.addressCity`            | string            |
| `address.addressCountry`         | string            |

All other Company fields are left to Twenty defaults.

## 6. Field Mapping

| SOAP source                        | Twenty target                        | Transform                         |
|------------------------------------|--------------------------------------|-----------------------------------|
| `s0:Company/s0:Name`               | `name`                               | trim                              |
| `s0:Company/s0:Website`            | `domainName.primaryLinkUrl`          | trim, lowercase scheme+host       |
| (constant `""`)                    | `domainName.primaryLinkLabel`        | always empty                      |
| (constant `[]`)                    | `domainName.secondaryLinks`          | always empty array                |
| `s0:Company/s0:Address`            | `address.addressStreet1`             | trim                              |
| `s0:Company/s0:City`               | `address.addressCity`                | trim                              |
| `s0:Company/s0:Country`            | `address.addressCountry`             | trim                              |

When the source value is missing or empty after trimming:

- For `name`: the row MUST be skipped and logged.
- For any other mapped field: the field MUST be omitted from the request body
  (do not send empty strings or null inside the composite objects).

If `Website`, `Address`, `City`, and `Country` are all empty for a row, the
request body is just `{ "name": "<name>" }`.

## 7. Dedup Strategy

For each normalized row:

1. Query Twenty:
   ```
   GET /rest/companies
       ?filter=name[eq]:"<name>",deletedAt[is]:NULL
       &limit=1
       &depth=0
   ```
2. If `data.companies` is non-empty → log `skipped: already exists` and move
   on. The existing record is left untouched.
3. Otherwise → `POST /rest/companies?depth=0` with the mapped body.

The dedup key is exact-match `name` (case-sensitive, post-trim). Future work
may switch to a custom `erpId` field for stronger dedup; that is out of scope
for v1.

Within a single batch, the Polars normalizer also drops in-batch name
duplicates before any HTTP traffic, keeping the first occurrence by source
order. This avoids racing two `POST` calls for the same name.

## 8. SFTP Layout

The integration treats one directory on the SFTP server as the inbox and
maintains two sibling subfolders inside it:

```
<inbox>/                  # configured via SFTP_INBOX, e.g. ERPOut
├── *.xml                 # incoming files dropped by the ERP
├── processed/            # successfully ingested files (created on demand)
└── log/                  # per-run log files (created on demand)
```

Per-file lifecycle within a run:

1. The integration lists `<inbox>` (non-recursive) and selects regular files
   matching `*.xml`. `processed/` and `log/` are skipped.
2. Each candidate is downloaded to a local temp directory.
3. After all rows in that file are processed, the original is moved on the
   SFTP server to `<inbox>/processed/<original_name>`.
4. If a file with the same name already exists in `processed/`, the move
   target gets a timestamp suffix: `<base>.<UTC ISO8601>.xml`.

If the integration fails to parse a file at all (malformed XML, unreadable
bytes), the file is left in place and the failure is recorded in the run log
so the ERP team can investigate. Such files will be retried on the next run.

## 9. Run Lifecycle

The integration is invoked as `integration-x` (or
`python -m integration_x`) and executes one pass:

1. Load and validate config from environment.
2. Open the SFTP connection.
3. Ensure `processed/` and `log/` exist on the server (create if missing).
4. List candidate `*.xml` files.
5. For each candidate file:
   a. Download to a local temp path.
   b. Parse the SOAP envelope into a list of records.
   c. Build a Polars DataFrame; normalize and de-duplicate within batch.
   d. For each surviving row, run the dedup query, then create if absent.
   e. Move the file to `processed/`.
6. Upload the run log to `log/<UTC ISO8601>.log`.
7. Close the SFTP connection.
8. Exit with status `0` if every file was processed (with or without
   per-row skips), `1` if any file failed at the parse / move / upload step.

Concurrency: a single Integration-X process processes files sequentially.
Two simultaneous runs of the integration against the same inbox are not
supported. The external scheduler is responsible for not overlapping runs.

## 10. Error Handling

Failures are categorized:

| Category           | Example                                       | Action                                |
|--------------------|-----------------------------------------------|---------------------------------------|
| Config             | missing `TWENTY_API_TOKEN`                    | Fail fast before any I/O.             |
| SFTP connect       | host unreachable, auth failure                | Exit 1; nothing else attempted.       |
| File parse         | malformed XML in one file                     | Log, leave file in inbox, next file.  |
| Per-row validation | missing `Name`                                | Log row, skip, continue.              |
| Per-row Twenty     | 4xx/5xx from Twenty for one row               | Log row, skip, continue.              |
| Per-file archive   | SFTP move into `processed/` fails             | Log, exit 1 at end of run.            |
| Log upload         | SFTP write of log file fails                  | Print log to stderr, exit 1.          |

"Continue" means: the integration logs the failure, increments the skip
counter, and proceeds with the next row or file. It does not abort the batch.

## 11. Logging

A run log is built in memory and written to two destinations at the end of
the run:

- Local stdout (so the calling scheduler can capture it).
- SFTP `<inbox>/log/<UTC ISO8601>.log` (so the ERP team can audit drops).

Log format: one line per event, plain text, ISO-8601 UTC timestamps. Each
line is one of:

- `INFO  run_started`
- `INFO  file_found name=<filename>`
- `INFO  file_parsed name=<filename> rows=<n>`
- `INFO  row_created name="<company name>"`
- `WARN  row_skipped name="<company name>" reason=<duplicate|missing_name|api_error> detail=<short>`
- `WARN  file_skipped name=<filename> reason=<parse_error|other> detail=<short>`
- `INFO  file_archived name=<filename> destination=<path>`
- `INFO  run_summary files_total=<n> files_archived=<n> rows_total=<n> rows_created=<n> rows_skipped=<n>`
- `ERROR run_failed reason=<short>`

Logs MUST NOT contain the SFTP password or the Twenty bearer token, including
inside HTTP error bodies. Implementations are responsible for redacting
`Authorization` headers before logging any HTTP error.

## 12. Configuration

All configuration is read from environment variables. The CLI takes no
required arguments. Optional flags MAY be added (e.g. `--dry-run`,
`--inbox`), but the defaults must come from environment.

### 12.1 .env loading

At startup, before validating config, the CLI MUST load environment
variables from a `.env` file using the following resolution order:

1. The path passed via `--env-file <path>`, if provided.
2. `./.env` in the current working directory.

If no `.env` file is found, it is not an error — the CLI proceeds using
the process environment as-is. Variables already set in the process
environment MUST take precedence over values in `.env` (process env
wins). The reference implementation uses `python-dotenv` with
`override=False`.

A committed `.env.example` lists every supported variable with empty
values so a developer can `cp .env.example .env` and fill it in.

`.env` MUST be listed in `.gitignore` and MUST NOT be committed. In
production, the scheduler is expected to inject these variables via its
own secret manager rather than placing a `.env` on disk.

### 12.2 Variables

Required:

- `SFTP_HOST`           — e.g. `192.168.1.98`
- `SFTP_PORT`           — e.g. `2022`
- `SFTP_USERNAME`       — e.g. `viipipe`
- `SFTP_PASSWORD`       — secret, never logged
- `SFTP_INBOX`          — e.g. `ERPOut`
- `TWENTY_BASE_URL`     — e.g. `https://crm.mspixel.se`
- `TWENTY_API_TOKEN`    — secret, never logged

Optional:

- `INTEGRATION_X_TIMEOUT_SECONDS` — per-HTTP-request timeout. Default `30`.
- `INTEGRATION_X_LOG_LEVEL`       — `INFO` (default) or `DEBUG`.

## 13. Project Layout

```
integration-x/
├── SPEC.md                         # this document
├── README.md                       # short user-facing run instructions
├── pyproject.toml                  # Python package metadata + deps
├── src/integration_x/
│   ├── __init__.py
│   ├── __main__.py                 # `python -m integration_x` entry
│   ├── cli.py                      # argument parsing + run()
│   ├── config.py                   # env loading + validation
│   ├── sftp.py                     # SFTP list / download / move / upload
│   ├── parser.py                   # SOAP XML → list[dict]
│   ├── normalize.py                # Polars schema + transforms + dedup
│   ├── twenty.py                   # REST client (lookup + create)
│   ├── orchestrator.py             # the run() function tying it together
│   └── logging_setup.py            # log buffer + redaction
├── tests/
│   ├── fixtures/                   # sample Customers.xml etc.
│   ├── test_parser.py
│   ├── test_normalize.py
│   ├── test_twenty_client.py       # against a recorded fixture
│   └── test_orchestrator.py        # end-to-end with mocked SFTP+Twenty
├── docs/
│   ├── company.soap.xml            # reference SOAP payload
│   ├── twenty-crm.md               # vendored Twenty REST docs
│   └── crm.png                     # screenshot of the Twenty workspace
└── .agents/
    └── skills/twenty-crm/SKILL.md  # reusable Twenty REST skill
```

## 14. Out of Scope (Future Work)

Captured here so the v1 implementation does not drift into them:

- Mapping `OrgNumber`, `Industry`, `Phone`, `Email` once Twenty custom-field
  API names are agreed.
- Persisting the ERP `Id` on Twenty as a custom field, and switching dedup
  from `name` to that field.
- Updating existing Companies when source data changes.
- Creating Person records from `Email`/`Phone`.
- Reverse sync (Twenty → ERP).
- Multi-file transactional semantics. v1 commits each row as it goes.
- Deletion / soft-delete of Twenty records when source rows disappear.