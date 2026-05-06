---
name: twenty-crm
description: |
  Read and write records in a Twenty CRM workspace via its REST API.
  Use for listing, creating, updating, upserting, and deleting Twenty
  objects (Companies, People, Opportunities, Tasks, Notes, etc.).
---

# Twenty CRM REST

Use this skill whenever you need to talk to a Twenty CRM workspace
through its REST API. Twenty also exposes GraphQL, but this skill is
REST-only because that is what the integration uses.

## Auth and base URL

All requests use a bearer token, scoped to a workspace.

- Base URL: `$TWENTY_BASE_URL` (example: `https://crm.mspixel.se`)
- Token:    `$TWENTY_API_TOKEN` (workspace-scoped, generated in
            Settings → Playground)

Required header on every request:

```
Authorization: Bearer $TWENTY_API_TOKEN
```

Treat the token as a secret. Do not commit it. Do not echo it into
logs. Prefer short-lived Playground tokens during development.

## Endpoints in use

The REST API is rooted at `/rest`. Object endpoints follow a
plural-by-default REST convention.

- Core OpenAPI schema: `GET /rest/open-api/core?token=...`
- Metadata OpenAPI schema: `GET /rest/open-api/metadata?token=...`
- Object collection: `GET|POST|DELETE /rest/<objects>`
- Single record: `GET|PATCH|DELETE /rest/<objects>/<id>`

`<objects>` is the plural object name as it appears in Twenty
(`companies`, `people`, `opportunities`, `tasks`, `notes`, ...).

When you need an unfamiliar field or endpoint, fetch the OpenAPI
schema first and grep it. Do not guess field names.

## Listing records

```
GET /rest/companies?limit=60
```

Useful query parameters:

- `limit` — page size, default 60, max 60 (some endpoints allow up to
  200; check the schema).
- `order_by` — `field1,field2[Direction2]`. Directions:
  `AscNullsFirst`, `AscNullsLast`, `DescNullsFirst`, `DescNullsLast`.
- `filter` — see below.
- `depth` — `0` for primary record only, `1` (default) to include
  direct relations.
- `starting_after`, `ending_before` — cursor pagination from
  `pageInfo.endCursor` / `pageInfo.startCursor`.

Response shape:

```
{
  "data": { "companies": [ ... ] },
  "pageInfo": {
    "hasNextPage": true,
    "startCursor": "...",
    "endCursor": "..."
  },
  "totalCount": 1
}
```

## Filter syntax

Format: `field[COMPARATOR]:value`. Multiple conditions are
comma-separated and AND-joined at the root.

Comparators: `eq`, `neq`, `in`, `containsAny`, `is`, `gt`, `gte`,
`lt`, `lte`, `startsWith`, `like`, `ilike`.

- Strings and dates are quoted; numbers and booleans are not.
- For `like`/`ilike`, use `%` as a wildcard.
- Composite fields use dot notation: `owner.name[ilike]:"%smith%"`.
- `[is]:NULL` checks for null. Pair with `deletedAt[is]:NULL` to
  exclude soft-deleted rows.
- `[in]` takes a JSON array: `id[in]:["id-1","id-2"]`.

Boolean groupings (optional):

```
filter=or(status[eq]:"open",assigneeId[is]:NULL)
filter=and(createdAt[gte]:"2024-01-01",isActive[eq]:true)
filter=not(idealCustomerProfile[eq]:true)
```

`not(...)` wraps exactly one condition.

## Creating records

```
POST /rest/companies
Content-Type: application/json

{
  "name": "Northwind Traders",
  "domainName": {
    "primaryLinkLabel": "",
    "primaryLinkUrl": "https://northwind.example",
    "secondaryLinks": []
  }
}
```

- Use `?upsert=true` to create-or-update by Twenty's natural key for
  the object. Behavior is per-object; verify against the OpenAPI
  schema before relying on it.
- Use `?depth=0` to get back the primary record only and skip the
  large relation payload.

Composite field shapes you will hit on `companies`:

- `domainName`, `linkedinLink`, `xLink` — link objects with
  `primaryLinkLabel`, `primaryLinkUrl`, `secondaryLinks`.
- `address` — `addressStreet1`, `addressStreet2`, `addressCity`,
  `addressPostcode`, `addressState`, `addressCountry`, `addressLat`,
  `addressLng`.
- `annualRecurringRevenue`, `annualLicenseCommitment` —
  `{ "amountMicros": <integer>, "currencyCode": "EUR" }`. Note
  micros: `1.50 EUR` becomes `amountMicros: 1500000`.

## Updating records

Single-record update:

```
PATCH /rest/companies/<id>
Content-Type: application/json

{ "employees": 42 }
```

Bulk update by filter (when supported by the object):

```
PATCH /rest/companies?filter=name[eq]:"Northwind Traders"
{ "currentWorkatoCustomer": true }
```

Bulk endpoints accept `filter` and `depth` like the list endpoint.

## Deleting records

- Single: `DELETE /rest/companies/<id>`
- Bulk by filter: `DELETE /rest/companies?filter=...`
- `?soft_delete=true` to soft-delete instead of hard-delete; default
  is hard delete on bulk endpoints. Verify per object.

To find soft-deleted rows later, filter with
`deletedAt[is]:NOT_NULL`.

## Schema discovery

When you hit an unfamiliar field, custom object, or enum value:

1. Fetch the workspace OpenAPI schema:

   ```
   GET /rest/open-api/core?token=$TWENTY_API_TOKEN
   GET /rest/open-api/metadata?token=$TWENTY_API_TOKEN
   ```

2. Search the schema for the object or field name.
3. Use the field exactly as it appears (custom field API names are
   workspace-specific and may differ from the UI label).

Custom fields show up as additional top-level keys on the object
payload, not under a separate `customFields` map.

## Usage rules

- Read the OpenAPI schema before assuming a field exists, especially
  for custom fields.
- Send minimal payloads. Use `depth=0` and explicit `order_by` /
  `filter` to keep responses small.
- Treat the bearer token as a secret. Read it from an environment
  variable; never inline it into committed code or commit messages.
- Idempotency: prefer `?upsert=true` or a search-then-update flow
  over blind `POST` when the same source data may be replayed.
- Pagination: always check `pageInfo.hasNextPage` and follow
  `endCursor` until exhausted. Do not rely on `totalCount` for
  termination.
- Filter dates and strings with quotes; do not quote numbers or
  booleans.
- For monetary fields, always pass `amountMicros` (integer) plus
  `currencyCode`.