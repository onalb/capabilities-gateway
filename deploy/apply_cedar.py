"""Create the vacancy identity, the two caller roles, and the Cedar permits.

The deal identity cre_deal_rentroll_wli already exists. This script creates
cre_vacancy_wli, attaches an ENFORCE policy engine to the one gateway, and
publishes the tools Lambda that the gateway target invokes.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AWS = os.environ.get("AWS_CLI", r"C:\Program Files\Amazon\AWSCLIV2\aws.exe")
REGION = "us-east-1"
ACCOUNT = "226721156429"
GATEWAY = "credealrentroll-25yvwacjrd"
TARGET_ID = "QZAHMOBLU1"
FUNCTION = "cre-deal-rentroll-gateway"
sys.path.insert(0, str(ROOT))

from capabilities_gateway.permits import (  # noqa: E402
    DEAL_IDENTITY,
    DEAL_ROLE,
    GATEWAY_ARN,
    VACANCY_IDENTITY,
    VACANCY_ROLE,
    cedar_statement,
    gateway_tool_schemas,
    role_arn,
)


def aws(*args: str) -> tuple[int, str]:
    proc = subprocess.run(
        [AWS, *args, "--region", REGION, "--output", "json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, (proc.stdout or proc.stderr or "")


def aws_json(*args: str) -> dict:
    code, text = aws(*args)
    if code != 0:
        raise SystemExit(text[:800])
    return json.loads(text) if text.strip() else {}


def ensure_role(name: str) -> None:
    trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"AWS": f"arn:aws:iam::{ACCOUNT}:root"},
                "Action": "sts:AssumeRole",
            }
        ],
    }
    code, text = aws("iam", "get-role", "--role-name", name)
    if code != 0:
        path = Path(tempfile.gettempdir()) / f"trust-{name}.json"
        path.write_text(json.dumps(trust), encoding="utf-8")
        aws_json("iam", "create-role", "--role-name", name, "--assume-role-policy-document", f"file://{path}")
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": "bedrock-agentcore:InvokeGateway",
                "Resource": GATEWAY_ARN,
            }
        ],
    }
    doc = Path(tempfile.gettempdir()) / f"invoke-{name}.json"
    doc.write_text(json.dumps(policy), encoding="utf-8")
    aws_json("iam", "put-role-policy", "--role-name", name, "--policy-name", "invoke-gateway", "--policy-document", f"file://{doc}")


def ensure_identity(name: str) -> None:
    code, _text = aws("bedrock-agentcore-control", "get-workload-identity", "--name", name)
    if code == 0:
        print("identity exists", name)
        return
    aws_json("bedrock-agentcore-control", "create-workload-identity", "--name", name)
    print("created identity", name)


def publish_lambda() -> None:
    work = Path(tempfile.gettempdir()) / "cre-tools-lambda"
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    shutil.copytree(ROOT / "capabilities_gateway", work / "capabilities_gateway", ignore=shutil.ignore_patterns("__pycache__"))
    installed = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{work}:/out",
            "python:3.12-slim",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-cache-dir",
            "mcp==2.1.1",
            "httpx",
            "pydantic",
            "ddgs",
            "openpyxl",
            "azure-identity",
            "azure-storage-blob",
            "-t",
            "/out",
        ],
    )
    if installed.returncode != 0:
        raise SystemExit(installed.returncode)
    zip_path = Path(tempfile.gettempdir()) / "cre-tools-lambda.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in work.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                zf.write(path, path.relative_to(work).as_posix())
    print("lambda zip", zip_path.stat().st_size)
    aws_json(
        "lambda",
        "update-function-code",
        "--function-name",
        FUNCTION,
        "--zip-file",
        f"fileb://{zip_path}",
    )
    for _ in range(20):
        data = aws_json("lambda", "get-function-configuration", "--function-name", FUNCTION)
        if data.get("LastUpdateStatus") in {None, "Successful"} and data.get("State") == "Active":
            break
        time.sleep(3)
    aws_json(
        "lambda",
        "update-function-configuration",
        "--function-name",
        FUNCTION,
        "--handler",
        "capabilities_gateway.gateway_target.lambda_handler",
        "--timeout",
        "60",
        "--environment",
        "Variables={DDB_TABLE=ml_interview,DDB_USE_AWS=1,VACANCY_FIT_DIR=/tmp/fits}",
    )
    print("lambda handler updated")


def update_target() -> None:
    schema = {
        "mcp": {
            "lambda": {
                "lambdaArn": f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{FUNCTION}",
                "toolSchema": {"inlinePayload": gateway_tool_schemas()},
            }
        }
    }
    path = Path(tempfile.gettempdir()) / "gw-target.json"
    path.write_text(json.dumps(schema), encoding="utf-8")
    cred = Path(tempfile.gettempdir()) / "gw-cred.json"
    cred.write_text(json.dumps([{"credentialProviderType": "GATEWAY_IAM_ROLE"}]), encoding="utf-8")
    aws_json(
        "bedrock-agentcore-control",
        "update-gateway-target",
        "--gateway-identifier",
        GATEWAY,
        "--target-id",
        TARGET_ID,
        "--name",
        "cretools",
        "--target-configuration",
        f"file://{path}",
        "--credential-provider-configurations",
        f"file://{cred}",
    )
    print("gateway target schema updated")


def ensure_engine() -> str:
    code, text = aws("bedrock-agentcore-control", "list-policy-engines")
    if code == 0:
        for item in json.loads(text).get("policyEngines") or json.loads(text).get("items") or []:
            if item.get("name") == "cre_mcp_policy":
                engine_id = item.get("policyEngineArn") or item.get("policyEngineId") or item.get("id")
                print("engine exists", engine_id)
                return str(engine_id)
    created = aws_json(
        "bedrock-agentcore-control",
        "create-policy-engine",
        "--name",
        "cre_mcp_policy",
    )
    engine_id = (
        created.get("policyEngineArn")
        or created.get("policyEngineId")
        or (created.get("policyEngine") or {}).get("policyEngineArn")
        or created.get("id")
    )
    print("created engine", engine_id)
    return str(engine_id)


def attach_engine(engine_id: str) -> None:
    current = aws_json("bedrock-agentcore-control", "get-gateway", "--gateway-identifier", GATEWAY)
    arn = engine_id if engine_id.startswith("arn:") else (
        f"arn:aws:bedrock-agentcore:{REGION}:{ACCOUNT}:policy-engine/{engine_id}"
    )
    role = current.get("roleArn")
    name = current.get("name") or "credealrentroll"
    authorizer = current.get("authorizerType") or "AWS_IAM"
    aws_json(
        "bedrock-agentcore-control",
        "update-gateway",
        "--gateway-identifier",
        GATEWAY,
        "--name",
        name,
        "--role-arn",
        role,
        "--authorizer-type",
        authorizer,
        "--policy-engine-configuration",
        f"arn={arn},mode=ENFORCE",
    )
    print("attached", arn, "ENFORCE")


def ensure_policy(engine_id: str, name: str, statement: str) -> None:
    engine_id = engine_id.split("/")[-1]
    definition = {"cedar": {"statement": statement}}
    path = Path(tempfile.gettempdir()) / f"{name}.json"
    path.write_text(json.dumps(definition), encoding="utf-8")
    code, text = aws(
        "bedrock-agentcore-control",
        "create-policy",
        "--policy-engine-id",
        engine_id,
        "--name",
        name,
        "--definition",
        f"file://{path}",
    )
    print(name, code, text[:300].replace("\n", " "))


def main() -> int:
    if os.environ.get("ONLY_PUBLISH") == "1":
        publish_lambda()
        return 0
    ensure_role(DEAL_ROLE)
    ensure_role(VACANCY_ROLE)
    ensure_identity(DEAL_IDENTITY)
    ensure_identity(VACANCY_IDENTITY)
    print("deal role", role_arn(DEAL_ROLE))
    print("vacancy role", role_arn(VACANCY_ROLE))
    if os.environ.get("SKIP_PUBLISH") != "1":
        publish_lambda()
        update_target()
    engine_id = ensure_engine()
    attach_engine(engine_id)
    ensure_policy(engine_id, "allow_deal_tools", cedar_statement("deal"))
    ensure_policy(engine_id, "allow_vacancy_tools", cedar_statement("vacancy"))
    print("engine", engine_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
