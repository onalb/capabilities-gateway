# Capabilities gateway

This process serves skills over HTTP: `GET /skills` and `GET /skills/{name}`. It is not the MCP server.

Deal and vacancy call one AgentCore MCP. Each app assumes its identity role, and the policy engine permits only that identity's tools. The gateway invokes Lambda `cre-deal-rentroll-gateway`, handler `capabilities_gateway.gateway_target.lambda_handler`. `score_gcr` is not a tool here; the deal app has its own Lambda for that judge.

| Identity | Role | Tools |
| --- | --- | --- |
| `cre_deal_rentroll_wli` | `CreDealRentrollWli` | `cre_ping`, `query_units`, `compute_income`, `compute_noi`, `compute_cap_rate`, `osm_geocode`, `web_search`, `publish_memo`, `ask_prediction_agent`, `create_plan`, `update_plan`, `update_plan_status`, `reflection` |
| `cre_vacancy_wli` | `CreVacancyWli` | `parse_rent_roll_file`, `fit_vacancy`, `list_trained_properties`, `load_fit`, `save_fit`, `delete_fit`, `score_vacancy`, `create_plan`, `update_plan`, `update_plan_status`, `reflection` |

`ask_prediction_agent` forwards `{question, session_id, plan_table}` to the vacancy app's own `POST /mcp` tool `ask_vacancy` (`VACANCY_MCP_URL`). That forward stays inside the tools handler. `plan_table` is attached server-side from the user's vault roll (aggregated per-plan group counts, fit transiently on the vacancy session, never saved); when the question names a different building or there is no roll, nothing is attached. `ask_vacancy` is not on this MCP. Floor-plan vacancy probability is `ask_prediction_agent` too — the in-gateway `ask_vacancy_agent` fit is gone.

Skills: `GET /skills` and `GET /skills/{name}` return markdown (`rent-roll-abstract`, `citation-policy`, `underwriting`, `rr-predict`, `vacancy`). They stay HTTP. They are not Lambda and not MCP tools.

## Tools Lambda

Handler: `capabilities_gateway.tools_lambda.handler`.

Event: `{"tool": "<name>", "arguments": {...}}`. Checklist calls also send `"route": "deal"` or `"route": "vacancy"`. The gateway wrapper adds `route`. It is not an MCP argument, so the tool menus stay the same.

`TOOLS_LAMBDA_ARN` unset or blank: this process calls that handler in-process. Local docker and pytest need no AWS account.

`TOOLS_LAMBDA_ARN` set: this process calls `lambda.invoke` on that ARN with `boto3`. The deal and vacancy apps still post to this MCP server. They do not call the Lambda.

Saved fits are not kept in process memory. Each call reads `VACANCY_FIT_DIR` (default `data/fits`) or Azure Blob when `AZURE_STORAGE_ACCOUNT` is set and a storage token works. Local runs use the directory. A deployed Lambda should set the Azure account, or a durable `VACANCY_FIT_DIR`, because Lambda disk does not keep fits across cold starts.

`parse_rent_roll_file` reads `content_base64` from the arguments. It does not need a file that exists only on the vacancy machine.

`delete_fit` deletes only when `confirm` is true. The vacancy app holds the pending question on its session and sends `confirm=true` after the user agrees to that same scope. This handler does not ask the user.

## Run locally

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m capabilities_gateway
```

Listens on `0.0.0.0:8010` (`PORT` overrides). JSON skill responses.

Docker:

```powershell
docker compose up -d --build
```

## How the agents choose

Set `CAPABILITIES_GATEWAY_URL` (example `http://127.0.0.1:8010`) for skills. Set `MCP_URL` to the AgentCore gateway for tools.

- Deal assumes `CreDealRentrollWli` and posts tools to `MCP_URL`. Skills are fetched from `{CAPABILITIES_GATEWAY_URL}/skills/{name}`. `score_gcr` is a separate Lambda the deal app invokes. It is not a tool on this MCP. The deal app sends the current checklist plus `last_work_tool` and `last_work_status`, and stores the checklist the gateway returns. On vault reads it also sends the roll snapshot.
- Vacancy assumes `CreVacancyWli` and posts its tools to the same `MCP_URL`. The vacancy skill is fetched from `{CAPABILITIES_GATEWAY_URL}/skills/vacancy`. `ask_vacancy` stays on the vacancy app. When `MCP_URL` is unset, the math tools stay local. The vacancy app still base64-forwards the upload and still sends `delete_fit` with `confirm=true` only after its session gate.

`delete_fit` deletes a fit file only when the call includes `confirm=true`. The vacancy app holds the pending confirmation on the chat session and sends `confirm=true` only after the user agrees to that same scope.

## Env

| Variable | Role |
| --- | --- |
| `PORT` | Listen port, default `8010` |
| `TOOLS_LAMBDA_ARN` | Tools Lambda. Unset calls `capabilities_gateway.tools_lambda.handler` in this process. Set calls `lambda.invoke`. Not used for skills or `score_gcr`. |
| `VACANCY_MCP_URL` | Vacancy app `POST /mcp`. Local compose uses the host app at `http://host.docker.internal:8000/mcp`. Unset in a bare process uses the public vacancy container. Must not be this gateway. |
| `DDB_ENDPOINT` | Deal Dynamo (local compose is `http://127.0.0.1:8003`). Unset uses an in-memory vault. |
| `DDB_TABLE` | Default `ml_interview` |
| `DDB_USE_AWS` | `1` to use real AWS when `DDB_ENDPOINT` is unset. Leave unset for local runs. |
| `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | Dynamo credentials. Local Dynamo accepts `local` / `local`. |
| `AZURE_STORAGE_ACCOUNT` | When set (and a storage token works), vacancy fits use that blob account. Set this on a deployed tools Lambda so fits survive the next call. |
| `AZURE_STORAGE_CONTAINER` | Default `fits` |
| `VACANCY_FIT_DIR` | Directory store when Azure is unset. Default `data/fits`. Local docker and pytest use this and do not need AWS. |
| `CAPABILITIES_SKILLS_DIR` | Skill markdown root. Default `skills/` in this repo. |

Deal and vacancy apps read `CAPABILITIES_GATEWAY_URL`. This process does not.
