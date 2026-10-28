# Capabilities gateway

One MCP server both agents call. It is not an AgentCore gateway.

This process stays up. It is the MCP server (`POST /mcp/deal` and `POST /mcp/vacancy`) and it serves `GET /skills` and `GET /skills/{name}`. Every tool on those two paths runs in one Lambda, `capabilities_gateway.tools_lambda.handler`. This process invokes that Lambda. The deal and vacancy apps do not. Skills are not Lambda and not MCP tools. `score_gcr` is not a tool here; the deal app has its own Lambda for that judge.

The allowlist is the URL. There is no password.

| Caller | Path | Tools |
| --- | --- | --- |
| Deal agent | `POST /mcp/deal` | `query_units`, `compute_income`, `compute_noi`, `compute_cap_rate`, `osm_geocode`, `web_search`, `publish_memo`, `ask_vacancy_agent`, `ask_prediction_agent`, `create_plan`, `update_plan`, `update_plan_status`, `reflection` |
| Vacancy agent | `POST /mcp/vacancy` | `parse_rent_roll_file`, `fit_vacancy`, `list_trained_properties`, `load_fit`, `save_fit`, `delete_fit`, `score_vacancy`, `create_plan`, `update_plan`, `update_plan_status`, `reflection` |

`ask_prediction_agent` on `/mcp/deal` forwards `{question, session_id}` to the vacancy app's own `POST /mcp` tool `ask_vacancy` (`VACANCY_MCP_URL`). That forward stays inside the tools handler. `ask_vacancy` is not moved into the Lambda. `ask_vacancy_agent` scores floor-plan vacancy on that user's vault roll in the tools handler and does not call the vacancy app. The vacancy app does not call `/mcp/deal`, so the two directions do not loop. There is no `/mcp/deal` tool named `ask_vacancy`.

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

Listens on `0.0.0.0:8010` (`PORT` overrides). JSON responses, no redirect from `/mcp/deal` or `/mcp/vacancy`.

Docker:

```powershell
docker compose up -d --build
```

## How the agents choose

Set `CAPABILITIES_GATEWAY_URL` (example `http://127.0.0.1:8010`) on the deal app and the vacancy app.

- Deal: the nine capability tools and the four checklist tools post to `{URL}/mcp/deal`. This process then runs the tools handler (in-process, or the Lambda when `TOOLS_LAMBDA_ARN` is set). Skills are fetched from `{URL}/skills/{name}`. `score_gcr` is a separate Lambda the deal app invokes. It is not a tool on this gateway. When `CAPABILITIES_GATEWAY_URL` is unset, those tools return an error that the capabilities gateway is required. They do not run in the deal process. The deal app sends the current checklist plus `last_work_tool` and `last_work_status`, and stores the checklist the gateway returns.
- Vacancy: `parse_rent_roll_file`, `fit_vacancy`, `list_trained_properties`, `load_fit`, `save_fit`, `delete_fit`, `score_vacancy`, and the same four checklist tools post to `{URL}/mcp/vacancy`. The vacancy skill is fetched from `{URL}/skills/vacancy` and pasted into the agent instructions. `ask_vacancy` stays on the vacancy app. When the variable is unset, the math tools stay local. The checklist tools and the agent return an error that the capabilities gateway is required. The vacancy app holds the checklist the same way the deal app does. The vacancy app still base64-forwards the upload and still sends `delete_fit` with `confirm=true` only after its session gate.

`delete_fit` is on `POST /mcp/vacancy` only. This gateway is stateless. It deletes a fit file only when the call includes `confirm=true`. The vacancy app holds the pending confirmation on the chat session and sends `confirm=true` only after the user agrees to that same scope. A direct call to this gateway is not a user prompt. The model-facing vacancy tool still requires the two-step flow and does not forward `confirm=true` until that session check passes, so the model cannot skip the user.

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
