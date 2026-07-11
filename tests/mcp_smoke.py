"""Verify MCP initialization, tool discovery, and backend registry access."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


ROOT = Path(__file__).resolve().parents[1]


async def run() -> None:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(ROOT / "mcp_server" / "mining_mcp_server.py"), "--transport", "stdio"],
    )
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            expected = {
                "list_backends", "backend_capabilities", "inspect_dataset", "validate_local_project", "run_gee_export",
                "run_envi_classification", "run_arcgis_operations", "run_plus_scenario",
                "run_invest_carbon", "validate_lulc_model", "run_pytorch_lulc", "evaluate_ecosystem_services",
                "get_job_status", "cancel_job", "list_job_outputs",
            }
            missing = expected - names
            if missing:
                raise AssertionError(f"missing MCP tools: {sorted(missing)}")
            result = await session.call_tool("list_backends", {})
            payload = json.loads(result.content[0].text)
            if not {"gee", "envi", "plus", "arcgis", "invest", "pytorch", "project", "ecosystem"}.issubset(payload["backends"]):
                raise AssertionError("backend registry is incomplete")
            invalid_re = await session.call_tool("run_plus_scenario", {
                "project": "example", "scenario": "RE", "workspace": str(ROOT / "outputs"), "parameters": {}
            })
            invalid_re_payload = json.loads(invalid_re.content[0].text)
            if invalid_re_payload.get("status") != "failed" or "resource_extraction" not in invalid_re_payload.get("error", ""):
                raise AssertionError(f"RE input contract was not enforced: {invalid_re_payload}")
            project_file = ROOT / "tests" / "fixtures" / "local_project" / "project.json"
            project_result = await session.call_tool("validate_local_project", {"project_file": str(project_file)})
            project_validation = json.loads(project_result.content[0].text)
            if project_validation.get("status") != "completed":
                raise AssertionError(f"local project validation failed: {project_validation}")
            ecosystem_result = await session.call_tool("evaluate_ecosystem_services", {
                "criteria_table": str(ROOT / "tests" / "fixtures" / "ecosystem_criteria.csv"),
                "config": str(ROOT / "templates" / "ecosystem_service_config.json"),
                "output": str(ROOT / "outputs" / "mcp_ecosystem_smoke.csv"),
            })
            ecosystem = json.loads(ecosystem_result.content[0].text)
            if ecosystem.get("status") != "completed":
                raise AssertionError(f"ecosystem MCP evaluation failed: {ecosystem}")
            capability_result = await session.call_tool("backend_capabilities", {"backend": "arcgis"})
            capability = json.loads(capability_result.content[0].text)
            if capability.get("status") != "completed":
                raise AssertionError(f"local command bridge failed: {capability}")
            end_to_end = {}
            model_package = ROOT / "tests" / "fixtures" / "model_package"
            model_result = await session.call_tool("validate_lulc_model", {"model_package": str(model_package)})
            model_validation = json.loads(model_result.content[0].text)
            if model_validation.get("status") != "completed":
                raise AssertionError(f"PyTorch model contract validation failed: {model_validation}")
            end_to_end["pytorch_model"] = model_validation["result"]["model_id"]
            end_to_end["local_project"] = project_validation["result"]["project_id"]
            end_to_end["ecosystem_method"] = ecosystem["result"]["method"]
            runtime_package = ROOT / "outputs" / "pytorch_smoke" / "model_package"
            runtime_input = ROOT / "outputs" / "pytorch_smoke" / "input.tif"
            if runtime_package.exists() and runtime_input.exists():
                torch_result = await session.call_tool("run_pytorch_lulc", {
                    "model_package": str(runtime_package), "input_raster": str(runtime_input),
                    "class_output": str(ROOT / "outputs" / "pytorch_smoke" / "mcp_lulc.tif"),
                    "confidence_output": str(ROOT / "outputs" / "pytorch_smoke" / "mcp_confidence.tif"),
                    "device": "cpu",
                })
                torch_inference = json.loads(torch_result.content[0].text)
                if torch_inference.get("status") != "completed":
                    raise AssertionError(f"PyTorch MCP inference failed: {torch_inference}")
                end_to_end["pytorch_inference"] = torch_inference["result"]["status"]
            raster = ROOT / "outputs" / "arcgis_smoke" / "lulc.tif"
            if raster.exists():
                inspected_result = await session.call_tool("inspect_dataset", {"path": str(raster)})
                inspected = json.loads(inspected_result.content[0].text)
                if inspected.get("status") != "completed" or inspected["result"].get("factory_code") != 32650:
                    raise AssertionError(f"ArcGIS MCP inspection failed: {inspected}")
                end_to_end["arcgis_crs"] = inspected["result"]["factory_code"]
            datastack = ROOT / "tests" / "invest_carbon_smoke_datastack.json"
            if datastack.exists() and raster.exists():
                invest_workspace = ROOT / "outputs" / "mcp_invest_smoke"
                invest_result = await session.call_tool("run_invest_carbon", {
                    "datastack": str(datastack), "workspace": str(invest_workspace)
                })
                invest = json.loads(invest_result.content[0].text)
                if invest.get("status") != "completed":
                    raise AssertionError(f"InVEST MCP run failed: {invest}")
                end_to_end["invest_outputs"] = len(invest.get("outputs", []))
            print(json.dumps({"tools": sorted(names), "backends": sorted(payload["backends"]),
                              "arcgis_bridge": capability["result"], "end_to_end": end_to_end}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(run())
