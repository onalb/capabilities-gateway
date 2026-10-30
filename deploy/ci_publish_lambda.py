"""Publish the tools Lambda and refresh the gateway target schema.

Code only. Function env vars are left as they are on the live function.
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

os.environ["AWS_PAGER"] = ""

ROOT = Path(__file__).resolve().parents[1]
REGION = "us-east-1"
FUNCTION = "cre-deal-rentroll-gateway"
GATEWAY = "credealrentroll-25yvwacjrd"
TARGET_ID = "QZAHMOBLU1"
ACCOUNT = "226721156429"
ZIP_LIMIT = 50 * 1024 * 1024

PIP_PACKAGES = [
    "mcp==2.1.1",
    "httpx",
    "pydantic",
    "ddgs",
    "openpyxl",
    "azure-identity",
    "azure-storage-blob",
    "python-dotenv",
]


def aws(*args: str) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["aws", *args, "--region", REGION],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        sys.stderr.write((proc.stderr or proc.stdout or "")[:800])
        raise SystemExit(proc.returncode)
    return proc


def function_config() -> dict:
    proc = aws(
        "lambda",
        "get-function-configuration",
        "--function-name",
        FUNCTION,
        "--query",
        "{sha:CodeSha256,status:LastUpdateStatus,state:State}",
        "--output",
        "json",
    )
    data = json.loads(proc.stdout)
    return {
        "sha": data.get("sha"),
        "status": data.get("status"),
        "state": data.get("state"),
    }


def build_zip(dest: Path) -> None:
    work = Path(tempfile.mkdtemp(prefix="cre-tools-lambda-"))
    try:
        shutil.copytree(
            ROOT / "capabilities_gateway",
            work / "capabilities_gateway",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        subprocess.run(
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
                *PIP_PACKAGES,
                "-t",
                "/out",
            ],
            check=True,
        )
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{work}:/out",
                "python:3.12-slim",
                "chmod",
                "-R",
                "a+rX",
                "/out",
            ],
            check=True,
        )
        with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in work.rglob("*"):
                if not path.is_file():
                    continue
                if "__pycache__" in path.parts or path.suffix == ".pyc":
                    continue
                zf.write(path, path.relative_to(work).as_posix())
    finally:
        shutil.rmtree(work, ignore_errors=True)


def update_gateway_target() -> None:
    sys.path.insert(0, str(ROOT))
    from capabilities_gateway.permits import gateway_tool_schemas

    schema = {
        "mcp": {
            "lambda": {
                "lambdaArn": f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{FUNCTION}",
                "toolSchema": {"inlinePayload": gateway_tool_schemas()},
            }
        }
    }
    tmp = Path(tempfile.mkdtemp(prefix="gw-target-"))
    try:
        target = tmp / "target.json"
        cred = tmp / "cred.json"
        target.write_text(json.dumps(schema), encoding="utf-8")
        cred.write_text(
            json.dumps([{"credentialProviderType": "GATEWAY_IAM_ROLE"}]),
            encoding="utf-8",
        )
        aws(
            "bedrock-agentcore-control",
            "update-gateway-target",
            "--gateway-identifier",
            GATEWAY,
            "--target-id",
            TARGET_ID,
            "--name",
            "cretools",
            "--target-configuration",
            f"file://{target}",
            "--credential-provider-configurations",
            f"file://{cred}",
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    zip_path = Path(tempfile.gettempdir()) / "cre-tools-lambda.zip"
    if zip_path.exists():
        zip_path.unlink()
    build_zip(zip_path)
    size = zip_path.stat().st_size
    print(f"lambda zip {size} bytes")
    if size > ZIP_LIMIT:
        print("lambda zip is over the 50 MB direct-upload limit", file=sys.stderr)
        return 1
    before = function_config()["sha"]
    aws(
        "lambda",
        "update-function-code",
        "--function-name",
        FUNCTION,
        "--zip-file",
        f"fileb://{zip_path}",
    )
    for _ in range(40):
        time.sleep(3)
        cur = function_config()
        if cur["status"] == "Failed":
            print("lambda update failed", file=sys.stderr)
            return 1
        if (
            cur["sha"]
            and cur["sha"] != before
            and cur["status"] in {None, "Successful"}
            and cur["state"] == "Active"
        ):
            break
    else:
        print("timed out waiting for lambda", file=sys.stderr)
        return 1
    print("lambda code updated")
    update_gateway_target()
    print("gateway target schema updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
