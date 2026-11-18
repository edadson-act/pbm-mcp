# pbm-mcp

MCP server for the Pharmacy Benefit Management APIs. It speaks streamable HTTP on `http://127.0.0.1:8000/mcp`. Tools are generated from OpenAPI or GraphQL files you drop in the repo. An allowlist decides which operations are actually exposed.

The server binds to localhost. Set `PBM_MCP_BEARER_TOKEN` before publishing the port with Tailscale Funnel. Callers send that secret as `Authorization: Bearer`. With the variable empty, `/mcp` accepts any caller who can reach the port.

## Run

```bash
uv sync
cp .env.example .env
uv run pbm-mcp
```

Cursor client config:

```json
{
  "mcpServers": {
    "pbm": {
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

With no spec files the process still starts and publishes no tools. A domain is mounted only when both its spec and its base URL are present.

## Local mock

`pbm-mock` answers the allowlisted GraphQL reads on `127.0.0.1:8001` so the MCP server can run without the live hosts. Leave `PBM_AUTH_MODE=none`. Point each `PBM_*_BASE_URL` at `http://127.0.0.1:8001/v1/<domain>/graphql` (the commented examples are in `.env.example`). MCP stays on port 8000. The Cursor client config stays the same.

```bash
uv run pbm-mock
uv run pbm-mcp
```

A request header `X-Mock-Status: 500` forces HTTP 500. `X-Mock-Status: graphql-error` forces HTTP 200 with a GraphQL `errors` array.

Responses resolve in this order:

1. `mocks/fixtures/<domain>/<operation>.json` replaces that operation.
2. `mocks/world` builds the allowlisted reads for the fictional member below.
3. Anything else is filled from the schema (`example-<field>`, one list item).

`mocks/world` describes a fictional commercial member, Jordan Hale, born 1984-03-12, ZIP 78701. Member id `MBR100200300`, carrier `CAR100`, account `ACC200`, group `GRP300`. Plan Commercial PPO 2026, formulary `DEMO-COMM-2026`. The individual deductible is met ($500 of $500) and out-of-pocket spend is $640 of $3,000. Prescriber Dr. Priya Shah. Pharmacies are Oak Street Pharmacy (current fill) and River City Pharmacy (preferred). These people, pharmacies, and identifiers are fictional. Do not put real member data in `mocks/world` or `mocks/fixtures`.

An omitted member id, name, or uuid is Jordan. A different member id returns an empty list, or a `CustomError` for `userProfile`. Drug name, NDC, GPI, and product id filter the catalog, case-insensitive. An unknown drug returns no rows, or a pricing header with no price rows. `claimDetails` returns a claim only when fill date, GPI, and claim number all match. A mismatch is a GraphQL error, `Claim not found.` Date ranges are not filters: the story claims stay in the response even when the requested window does not cover the fill date.

Prompts:

- Jordan Hale wants to know if they can pay less for their cholesterol medicine. Lipitor 20 mg was filled on 2026-10-02, claim `RX1002001`, GPI `39400010102001`, patient paid $47 at Oak Street Pharmacy. Generic atorvastatin at River City Pharmacy is $12, about $35 less. Neither drug needs prior authorization.
- Jordan Hale wants to know why their Humira was not covered and what has to happen next. The 2026-09-15 fill, claim `RX1002002`, GPI `66270015004001`, was rejected. Estimated patient responsibility is $6800. Prior authorization `PA-24011` is pending, and step therapy requires methotrexate first. Mail service is available and is not mandatory. Mail consent is not opted in.

## Specs

OpenAPI:

```text
specs/claim-history/openapi.yaml
allowlists/claim-history.yaml
```

`openapi.yml` and `openapi.json` are also accepted.

GraphQL introspection (the documents currently in `specs/`):

```text
specs/drug-search/drug-search-mp-api.yaml
allowlists/drug-search.yaml
```

The same pair exists for every catalog API. Allowlists include read fields only.

A file whose JSON contains `data.__schema` is read as introspection. Each root field can become a tool. `operations.graphql` is still accepted when you want to hand-write the query. A bare `schema.graphql` does not create tools. If a domain directory contains both an OpenAPI document and a GraphQL document, that domain is skipped.

Allowlist:

```yaml
operations:
  - id: listClaims
  - id: deleteClaim
    write: true
```

A missing or empty allowlist mounts the domain with zero tools. `GET`, `HEAD`, and `OPTIONS`, and GraphQL queries, can be listed by id. `POST`, `PUT`, `PATCH`, `DELETE`, and GraphQL mutations stay hidden unless the entry sets `write: true`. `orderIdCard` and `saveConsent` are queries in the schema and stay hidden the same way, because each one changes member state. Subscriptions are never exposed.

Tool names are `{namespace}_{operation}`, for example `claim_history_listClaims`.

## Endpoint auth

`PBM_MCP_BEARER_TOKEN` is a shared secret for callers of `/mcp`. It is separate from `PBM_BEARER_TOKEN`, which this server sends upstream. The value is the secret only, at least 16 characters:

```bash
openssl rand -hex 32
```

Put that value in `.env`. A request without `Authorization: Bearer <secret>` receives HTTP 401. The token is not written to logs.

Tailscale Funnel serves the local port on the public internet. Keep `PBM_HOST=127.0.0.1` and turn Funnel on after the token is set. Funnel has to be enabled for the tailnet.

```bash
tailscale funnel --bg 8000
```

The public URL is `https://<node>.<tailnet>.ts.net/mcp`. Cursor client config:

```json
{
  "mcpServers": {
    "pbm": {
      "url": "https://<node>.<tailnet>.ts.net/mcp",
      "headers": {
        "Authorization": "Bearer <PBM_MCP_BEARER_TOKEN>"
      }
    }
  }
}
```

`PBM_AUTH_MODE=forward` copies that same `Authorization` header onto upstream PBM calls. Use `bearer-env` or `api-key` for upstream credentials when the MCP token is the Funnel secret.

A non-loopback `PBM_HOST` refuses to start until `PBM_MCP_BEARER_TOKEN` is set.

## Auth

`PBM_AUTH_MODE` selects how this server calls the PBM APIs:

| Mode | Behavior |
| --- | --- |
| `none` | Send no credential |
| `api-key` | Header from `PBM_API_KEY` / `PBM_API_KEY_HEADER` (default `x-api-key`) |
| `bearer-env` | `Authorization: Bearer` from `PBM_BEARER_TOKEN` |
| `forward` | Copy the inbound MCP `Authorization` header onto the upstream call |
| `client-credentials` | Config slot only. A domain that selects it is skipped |

Override one API with `PBM_CLAIM_HISTORY_AUTH_MODE`, `PBM_CLAIM_HISTORY_API_KEY`, `PBM_CLAIM_HISTORY_BEARER_TOKEN`, or `PBM_CLAIM_HISTORY_API_KEY_HEADER`. Set `PBM_CLAIM_HISTORY_BASE_URL` to that API's origin or GraphQL endpoint. The same pattern applies to every catalog id: replace hyphens with underscores and uppercase the name.

`client-credentials` reads `PBM_TOKEN_URL`, `PBM_CLIENT_ID`, and `PBM_CLIENT_SECRET` but does not request a token yet.

## Member data

Profile, claims, ID cards, consent, and prior auth are member data. Request and response bodies are not logged. Logs contain the domain, operation name, status code, and latency. Upstream errors returned to the client are truncated and stripped of bearer tokens and assigned secrets.
