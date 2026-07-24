"""Pytest entry points for fast local/CI contract coverage."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("script", [
    "project_conditional_inputs_smoke.py", "project_builder_smoke.py", "project_workflow_smoke.py", "plus_re_contract_smoke.py",
    "native_resnet50_patch_smoke.py", "pytorch_template_contract_smoke.py", "registered_resnet50_real_inference.py",
    "envi_backend_smoke.py",
    "maesa_copilot_smoke.py", "project_backend_validation_smoke.py", "workflow_pending_validation_smoke.py",
    "project_task_modes_smoke.py", "stage_output_mapping_smoke.py",
    "plus_output_contract_smoke.py", "plus_v142_profile_smoke.py", "plus_bridge_state_isolation_smoke.py", "plus_chain_compile_smoke.py",
    "prepare_plus_scenarios_smoke.py",
    "invest_multimodel_compile_smoke.py", "invest_only_multimodel_builder_smoke.py",
    "invest_ecosystem_integration_smoke.py",
    "ecosystem_service_smoke.py", "ecosystem_sensitivity_smoke.py", "analysis_validation_smoke.py",
    "workflow_manifest_safety_smoke.py", "job_manager_smoke.py", "reliability_contract_smoke.py", "local_only_registry_smoke.py", "status_vocabulary_smoke.py", "release_metadata_smoke.py",
    "arcgis_layout_helpers_smoke.py",
    "real_raster_integration_smoke.py",
    "subsidence_water_carbon_smoke.py",
])
def test_contract_smokes(script: str) -> None:
    process = subprocess.run([sys.executable, str(ROOT / "tests" / script)], cwd=ROOT,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
    assert process.returncode == 0, process.stdout
