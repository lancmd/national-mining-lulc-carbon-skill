#!/usr/bin/env python3
"""Ask a configured LLM to plan a MAESA workflow without controlling software remotely."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
from pathlib import Path
from typing import Any
from urllib import error, request
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
VALID_PROVIDERS = {"ollama", "openai_compatible"}


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


def project_context(project: Path | None) -> dict[str, Any] | None:
    if project is None:
        return None
    payload = json.loads(project.expanduser().resolve().read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("project file must be a JSON object")
    return {"project_id": payload.get("project_id"), "classification": payload.get("classification", {}).get("enabled"),
            "plus": payload.get("plus", {}).get("enabled"), "invest": payload.get("invest", {}).get("enabled"),
            "ecosystem_service": payload.get("ecosystem_service", {}).get("enabled"),
            "gis_outputs": payload.get("gis_outputs", {}).get("enabled")}


def system_prompt(context: dict[str, Any] | None) -> str:
    return (
        "You are MAESA Copilot for mining-area ecological space analysis. "
        "Help users plan local workflows for LULC, PLUS, InVEST, subsidence-water carbon, ecosystem services and maps. "
        "Do not invent input files, numerical parameters, classification accuracy, PLUS outputs, or InVEST results. "
        "Recommend local MCP steps in this order: inspect capabilities, validate project, compile workflow, run local project, then validate outputs. "
        "You cannot remotely control ArcGIS Pro, ENVI, PLUS or InVEST; those operations remain local. "
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", type=Path, default=ROOT / "config" / "llm_provider.json")
    parser.add_argument("--message", required=True)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="Validate configuration and show the local request plan without contacting a model")
    args = parser.parse_args()
    try:
        provider = load_provider(args.provider.expanduser().resolve())
        context = project_context(args.project)
        if args.dry_run:
            result: dict[str, Any] = {"status": "prepared", "provider": provider["provider"], "model": provider["model"],
                                      "endpoint_is_local": is_loopback(str(provider["base_url"])), "project": context}
        else:
            result = {"status": "completed", "provider": provider["provider"], "model": provider["model"],
                      "reply": ask(provider, args.message, context)}
    except (OSError, ValueError, error.URLError, json.JSONDecodeError) as caught:
        result = {"status": "failed", "error": str(caught)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"prepared", "completed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
