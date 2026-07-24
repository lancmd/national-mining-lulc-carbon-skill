#!/usr/bin/env python3
"""Plan and, after explicit confirmation, run a controlled local MAESA MCP workflow."""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib import error, request
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
VALID_PROVIDERS = {"ollama", "openai_compatible"}
PLAN_SCHEMA_VERSION = 1
CONTROLLED_TOOLS = (
    "list_backends", "validate_local_project", "compile_project_workflow",
    "run_local_project", "validate_analysis_results",
)
PAUSE_STATUSES = {"prepared", "waiting_interactive", "pending_validation", "cancelled"}


def is_loopback(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def load_provider(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("LLM provider configuration must be a JSON object")
    provider = payload.get("provider")
    if provider not in VALID_PROVIDERS:
        raise ValueError(f"provider must be one of {sorted(VALID_PROVIDERS)}")
    base_url, model = payload.get("base_url"), payload.get("model")
    if not isinstance(base_url, str) or not base_url.startswith(("http://", "https://")):
        raise ValueError("base_url must be an http(s) URL")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("model must be a non-empty string")
    if not is_loopback(base_url) and payload.get("allow_cloud") is not True:
        raise ValueError("cloud LLM endpoints require allow_cloud: true; local endpoints are allowed by default")
    return payload


def load_project(path: Path) -> dict[str, Any]:
    payload = json.loads(path.expanduser().resolve().read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("project file must be a JSON object")
    return payload


def project_context(project: Path | None) -> dict[str, Any] | None:
    if project is None:
        return None
    payload = load_project(project)
    return {"project_id": payload.get("project_id"), "task_type": payload.get("task_type", "custom"),
            "classification": payload.get("classification", {}).get("enabled"),
            "plus": payload.get("plus", {}).get("enabled"), "invest": payload.get("invest", {}).get("enabled"),
            "ecosystem_service": payload.get("ecosystem_service", {}).get("enabled"),
            "gis_outputs": payload.get("gis_outputs", {}).get("enabled")}


def system_prompt(context: dict[str, Any] | None) -> str:
    return (
        "You are MAESA Copilot for mining-area ecological space analysis. "
        "Help users plan local workflows for LULC, PLUS, InVEST, subsidence-water carbon, ecosystem services and maps. "
        "Do not invent input files, numerical parameters, classification accuracy, PLUS outputs, or InVEST results. "
        "Desktop software is local-only. You cannot issue shell commands or network software-control requests. "
        f"Current project summary: {json.dumps(context or {}, ensure_ascii=False)}"
    )


def post_json(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
    req = request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers=headers, method="POST")
    with request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def ask(provider: dict[str, Any], message: str, context: dict[str, Any] | None) -> str:
    base_url = str(provider["base_url"]).rstrip("/")
    timeout = float(provider.get("timeout_seconds", 90))
    messages = [{"role": "system", "content": system_prompt(context)}, {"role": "user", "content": message}]
    if provider["provider"] == "ollama":
        reply = post_json(base_url + "/api/chat", {"model": provider["model"], "messages": messages, "stream": False},
                          {"Content-Type": "application/json"}, timeout)
        content = reply.get("message", {}).get("content")
    else:
        endpoint = base_url if base_url.endswith("/chat/completions") else base_url + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        key_name = provider.get("api_key_env")
        if isinstance(key_name, str) and key_name:
            key = os.getenv(key_name)
            if not key:
                raise ValueError(f"environment variable is not set: {key_name}")
            headers["Authorization"] = f"Bearer {key}"
        reply = post_json(endpoint, {"model": provider["model"], "messages": messages, "temperature": 0.2}, headers, timeout)
        choices = reply.get("choices", [])
        content = choices[0].get("message", {}).get("content") if choices else None
    if not isinstance(content, str) or not content.strip():
        raise ValueError("LLM response did not contain text")
    return content.strip()


def workspace_for(project_file: Path, project: dict[str, Any]) -> Path:
    raw = project.get("workspace")
    if not isinstance(raw, str) or not raw:
        raise ValueError("project workspace is required for an execution plan")
    value = Path(raw).expanduser()
    return value.resolve() if value.is_absolute() else (project_file.parent / value).resolve()


PATH_LEAF_KEYS = {
    "path", "imagery", "lulc_baseline", "historical_lulc", "mine_boundary", "carbon_density", "model_package",
    "training_roi", "subsidence_w_dat", "subsidence_depth_raster", "dem", "workface_boundary",
    "aquatic_vegetation_boundary", "bottom_sediment_boundary", "subsidence_water_boundary",
    "validation_samples", "geodetector_samples", "datastack_template", "provided_datastack",
}


def looks_like_local_path(value: str) -> bool:
    suffixes = {".tif", ".tiff", ".img", ".gpkg", ".shp", ".geojson", ".csv", ".json", ".dat", ".txt", ".aprx", ".lyrx"}
    candidate = Path(value)
    return candidate.is_absolute() or "/" in value or "\\" in value or candidate.suffix.lower() in suffixes


def nested_input_paths(value: Any, key: str = "") -> list[str]:
    """Collect paths from dated imagery and nested driver/model definitions."""
    if isinstance(value, dict):
        return [item for child_key, child in value.items() for item in nested_input_paths(child, str(child_key))]
    if isinstance(value, list):
        return [item for child in value for item in nested_input_paths(child, key)]
    if isinstance(value, str) and value and (key in PATH_LEAF_KEYS or looks_like_local_path(value)):
        return [value]
    return []


def project_relative_path(project_file: Path, value: str) -> Path:
    candidate = Path(value).expanduser()
    return candidate.resolve() if candidate.is_absolute() else (project_file.parent / candidate).resolve()


def planned_inputs(project: dict[str, Any], project_file: Path | None = None) -> list[str]:
    values = nested_input_paths(project.get("inputs", {})) if isinstance(project.get("inputs"), dict) else []
    if project_file:
        return sorted({str(project_relative_path(project_file, value)) for value in values})
    return sorted(set(values))


def controlled_plan(project_file: Path, purpose: str) -> dict[str, Any]:
    project_file = project_file.expanduser().resolve()
    project = load_project(project_file)
    workspace = workspace_for(project_file, project)
    steps: list[dict[str, Any]] = [
        {"id": "capabilities", "tool": "list_backends", "arguments": {}},
        {"id": "validate_project", "tool": "validate_local_project", "arguments": {"project_file": str(project_file)}},
        {"id": "compile_workflow", "tool": "compile_project_workflow", "arguments": {
            "project_file": str(project_file), "output_job": str(workspace / "generated" / "workflow_job.json")}},
        {"id": "run_workflow", "tool": "run_local_project", "arguments": {
            "project_file": str(project_file), "output_job": str(workspace / "generated" / "workflow_job.json"),
            "dry_run": False, "continue_on_error": False, "confirm_overwrite": False}},
    ]
    validation = project.get("validation", {})
    if isinstance(validation, dict) and validation.get("enabled"):
        evidence_value = validation.get("evidence_file")
        evidence = (project_relative_path(project_file, str(evidence_value)) if evidence_value
                    else workspace / "validation" / "analysis_evidence.json")
        report_value = str(validation.get("output_report", "validation/analysis_validation_report.json"))
        report = project_relative_path(workspace / "project.json", report_value)
        steps.append({"id": "validate_results", "tool": "validate_analysis_results", "arguments": {
            "validation_file": str(evidence), "output_report": str(report)}})
    return {"schema_version": PLAN_SCHEMA_VERSION, "kind": "maesa_controlled_execution_plan",
            "project_file": str(project_file), "purpose": purpose, "task_type": project.get("task_type", "custom"),
            "expected_inputs": planned_inputs(project, project_file),
            "expected_outputs": [str(workspace / name) for name in ("outputs_manifest.json", "provenance.json", "validation_summary.json")],
            "steps": steps, "confirmation_required": True}


def extract_json(text: str) -> dict[str, Any]:
    candidate = text.strip()
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", candidate, flags=re.DOTALL | re.IGNORECASE)
    if match:
        candidate = match.group(1)
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as caught:
        raise ValueError("LLM did not return a JSON execution plan") from caught
    if not isinstance(payload, dict):
        raise ValueError("LLM execution plan must be a JSON object")
    return payload


def json_schema_errors(plan: dict[str, Any]) -> list[str]:
    """Run the shipped Draft 2020-12 schema when the MAESA validation extra is installed."""
    schema_path = ROOT / "schemas" / "maesa_execution_plan.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    try:
        from jsonschema import Draft202012Validator  # type: ignore
    except ImportError:
        # The fixed-contract checks below remain deliberately conservative for
        # a minimal standalone installation. The normal MAESA validation extra
        # installs jsonschema and exercises the complete document schema.
        required = schema.get("required", [])
        return [f"schema requires {name}" for name in required if name not in plan]
    return sorted(error.message for error in Draft202012Validator(schema).iter_errors(plan))


def validate_execution_plan(plan: dict[str, Any], project_file: Path) -> dict[str, Any]:
    """Validate schema and make the LLM plan match the fixed local tool contract."""
    expected = controlled_plan(project_file, str(plan.get("purpose", "execute MAESA project")))
    errors: list[str] = json_schema_errors(plan)
    if plan.get("schema_version") != PLAN_SCHEMA_VERSION:
        errors.append("schema_version must be 1")
    if plan.get("kind") != "maesa_controlled_execution_plan":
        errors.append("kind must be maesa_controlled_execution_plan")
    try:
        same_project = Path(str(plan.get("project_file", ""))).expanduser().resolve() == project_file.expanduser().resolve()
    except OSError:
        same_project = False
    if not same_project:
        errors.append("project_file must match the locally selected project")
    steps = plan.get("steps")
    if not isinstance(steps, list):
        errors.append("steps must be an array")
    else:
        expected_steps = expected["steps"]
        if [item.get("tool") for item in steps if isinstance(item, dict)] != [item["tool"] for item in expected_steps]:
            errors.append("steps must use the controlled capability-validate-compile-run-validate order")
        elif len(steps) == len(expected_steps):
            for actual, allowed in zip(steps, expected_steps):
                if not isinstance(actual, dict) or actual.get("arguments") != allowed["arguments"]:
                    errors.append(f"step {allowed['id']} arguments differ from the controlled local contract")
                    break
    if plan.get("confirmation_required") is not True:
        errors.append("confirmation_required must be true")
    return {"status": "valid" if not errors else "invalid", "errors": errors, "normalized_plan": expected}


def execution_prompt(project_file: Path, message: str) -> str:
    template = controlled_plan(project_file, message)
    return (
        "Return only one JSON execution plan. Do not add commands, URLs, or tools. "
        "The exact tool sequence and arguments must remain unchanged; you may only write a concise purpose.\n"
        + json.dumps(template, ensure_ascii=False, indent=2)
    )


async def execute_with_mcp(plan: dict[str, Any]) -> dict[str, Any]:
    """Invoke only the allowlisted local stdio MCP server tools."""
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError as caught:
        raise RuntimeError("MCP Python client is unavailable; install the MAESA runtime before executing a plan") from caught
    parameters = StdioServerParameters(command=sys.executable,
                                       args=[str(ROOT / "mcp_server" / "mining_mcp_server.py"), "--transport", "stdio"],
                                       env=dict(os.environ))
    records: list[dict[str, Any]] = []
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            available = {item.name for item in (await session.list_tools()).tools}
            for step in plan["steps"]:
                tool = step["tool"]
                if tool not in CONTROLLED_TOOLS or tool not in available:
                    return {"status": "failed", "records": records, "error": f"controlled MCP tool is unavailable: {tool}"}
                response = await session.call_tool(tool, step["arguments"])
                try:
                    payload = json.loads(response.content[0].text)
                except (IndexError, AttributeError, json.JSONDecodeError) as caught:
                    return {"status": "failed", "records": records, "error": f"invalid MCP response from {tool}: {caught}"}
                records.append({"id": step["id"], "tool": tool, "result": payload})
                status = payload.get("status")
                if status == "failed":
                    return {"status": "failed", "records": records, "error": payload.get("error", f"{tool} failed"),
                            "repair": "Correct the reported local project/input issue, then execute the same confirmed plan again."}
                if status in PAUSE_STATUSES:
                    return {"status": status, "records": records,
                            "resume": "Complete the indicated local handoff or validation, then re-run this same confirmed plan."}
    return {"status": "completed", "records": records}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", type=Path, default=ROOT / "config" / "llm_provider.json")
    parser.add_argument("--message")
    parser.add_argument("--project", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="Validate provider and preview a confirmation-gated plan without contacting a model")
    parser.add_argument("--write-execution-plan", type=Path, help="Ask the configured LLM for a constrained JSON plan and save it")
    parser.add_argument("--execute-plan", type=Path, help="Execute a previously validated local plan through stdio MCP")
    parser.add_argument("--confirm", action="store_true", help="Required acknowledgement before local MCP execution")
    args = parser.parse_args()
    try:
        if args.execute_plan:
            if not args.confirm:
                raise ValueError("--execute-plan requires --confirm; review the plan's inputs, steps, and outputs first")
            plan = load_project(args.execute_plan.expanduser().resolve())
            project_file = Path(str(plan.get("project_file", ""))).expanduser().resolve()
            checked = validate_execution_plan(plan, project_file)
            if checked["status"] != "valid":
                raise ValueError("execution plan validation failed: " + "; ".join(checked["errors"]))
            result = asyncio.run(execute_with_mcp(checked["normalized_plan"]))
        else:
            provider = load_provider(args.provider.expanduser().resolve())
            context = project_context(args.project)
            if args.dry_run:
                result = {"status": "pending_confirmation" if args.project else "prepared", "provider": provider["provider"],
                          "model": provider["model"], "endpoint_is_local": is_loopback(str(provider["base_url"])), "project": context}
                if args.project:
                    result["execution_plan"] = controlled_plan(args.project.expanduser().resolve(), args.message or "review project")
            else:
                if not args.message:
                    raise ValueError("--message is required unless --execute-plan is used")
                if args.write_execution_plan:
                    if not args.project:
                        raise ValueError("--write-execution-plan requires --project")
                    proposed = extract_json(ask(provider, execution_prompt(args.project.expanduser().resolve(), args.message), context))
                    checked = validate_execution_plan(proposed, args.project.expanduser().resolve())
                    if checked["status"] != "valid":
                        result = {"status": "failed", "errors": checked["errors"], "reply": proposed}
                    else:
                        destination = args.write_execution_plan.expanduser().resolve()
                        write_json(destination, checked["normalized_plan"])
                        result = {"status": "pending_confirmation", "provider": provider["provider"], "model": provider["model"],
                                  "execution_plan": str(destination), "plan": checked["normalized_plan"]}
                else:
                    result = {"status": "completed", "provider": provider["provider"], "model": provider["model"],
                              "reply": ask(provider, args.message, context)}
    except (OSError, ValueError, error.URLError, json.JSONDecodeError, RuntimeError) as caught:
        result = {"status": "failed", "error": str(caught)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"prepared", "pending_confirmation", "completed", *PAUSE_STATUSES} else 1


if __name__ == "__main__":
    raise SystemExit(main())
