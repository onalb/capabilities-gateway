# Capabilities gateway

One MCP server both agents call. It is not an AgentCore gateway.

The allowlist is the URL. There is no password.

| Caller | Path | Tools |
| --- | --- | --- |
| Deal agent | `POST /mcp/deal` | `query_units`, `compute_income`, `compute_noi`, `compute_cap_rate`, `osm_geocode`, `web_search`, `publish_memo`, `ask_vacancy` |
| Vacancy agent | `POST /mcp/vacancy` | `parse_rent_roll_file`, `fit_vacancy`, `load_fit`, `save_fit`, `score_vacancy` |

`ask_vacancy` on `/mcp/deal` forwards `{question, session_id}` to the vacancy app's own `POST /mcp` tool `ask_vacancy` (`VACANCY_MCP_URL`). The vacancy app does not call `/mcp/deal`, so the two directions do not loop.

Skills: `GET /skills` and `GET /skills/{name}` return markdown (`rent-roll-abstract`, `citation-policy`, `underwriting`, `rr-predict`, `vacancy`).

## Run locally

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m capabilities_gateway
```

Listens on `0.0.0.0:8010` (`PORT` overrides). JSON responses, no redirect from `/mcp/deal` or `/mcp/vacancy`.

Docker:

```powershell
docker compose up -d --build
```

## How the agents choose

Set `CAPABILITIES_GATEWAY_URL` (example `http://127.0.0.1:8010`) on the deal app and the vacancy app.

- Deal: capability tools and `ask_prediction_agent` post to `{URL}/mcp/deal`. Floor-plan questions use `ask_vacancy` on that path. Skills are fetched from `{URL}/skills/{name}`. Harness tools (`create_plan`, `update_plan`, `update_plan_status`, `reflection`, `score_gcr`) stay in the deal process. When the variable is unset, the deal app keeps in-process tools, disk skills, and `RR_PREDICT_URL`.
- Vacancy: `parse_rent_roll_file`, `fit_vacancy`, `load_fit`, `save_fit`, and `score_vacancy` post to `{URL}/mcp/vacancy`. `ask_vacancy` stays on the vacancy app. When the variable is unset, those tools stay local and the skill is `skills/vacancy/SKILL.md`.

## Env

| Variable | Role |
| --- | --- |
| `PORT` | Listen port, default `8010` |
| `VACANCY_MCP_URL` | Vacancy app `POST /mcp`. Default is the public vacancy container. Must not be this gateway. |
| `DDB_ENDPOINT` | Deal Dynamo (local compose is `http://127.0.0.1:8003`). Unset uses an in-memory vault. |
| `DDB_TABLE` | Default `ml_interview` |
| `DDB_USE_AWS` | `1` to use real AWS when `DDB_ENDPOINT` is unset. Leave unset for local runs. |
| `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | Dynamo credentials. Local Dynamo accepts `local` / `local`. |
| `AZURE_STORAGE_ACCOUNT` | When set (and a storage token works), vacancy fits use that blob account. |
| `AZURE_STORAGE_CONTAINER` | Default `fits` |
| `VACANCY_FIT_DIR` | Directory store when Azure is unset. Default `data/fits`. |
| `CAPABILITIES_SKILLS_DIR` | Skill markdown root. Default `skills/` in this repo. |

Deal and vacancy apps read `CAPABILITIES_GATEWAY_URL`. This process does not.
