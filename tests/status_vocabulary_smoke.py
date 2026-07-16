"""Keep the protocol status vocabulary consistent across code, templates, and documentation."""

from __future__ import annotations

import csv
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {"accepted", "running", "completed", "prepared", "pending_validation",
           "waiting_interactive", "failed", "cancelled"}
TEXT_SUFFIXES = {".md", ".json", ".csv", ".py", ".yaml", ".yml", ".ps1", ".toml", ".pro"}
SOURCE_PATHS = (
    "README.md", "SKILL.md", ".github", "agents", "arcgis_steps", "config", "deep_learning", "docs",
    "ecosystem_service", "envi_classification", "execution", "interfaces", "invest_carbon",
    "mcp_server", "open_gis_workflows", "plus_model", "scripts", "templates", "tests",
)


def source_files() -> list[Path]:
    """Return tracked-source locations, never virtualenvs or generated folders.

    The test checks MAESA's protocol vocabulary, not dependency source code.
    Scanning the whole worktree makes the result depend on whether a developer
    created a virtual environment called `.venv312`, `.tox`, or similar.
    """
    ignored_directory_names = {"outputs", "__pycache__", ".tox", "venv", "env", "site-packages"}
    files: list[Path] = []
    for relative in SOURCE_PATHS:
        candidate = ROOT / relative
        if candidate.is_file():
            files.append(candidate)
        elif candidate.is_dir():
            for path in candidate.rglob("*"):
                relative_parts = path.relative_to(ROOT).parts
                has_virtual_environment = any(part.casefold().startswith(".venv") for part in relative_parts)
                if path.is_file() and not has_virtual_environment and not any(part in ignored_directory_names for part in relative_parts):
                    files.append(path)
    return files

bare_pending = []
for path in source_files():
    if path.suffix.lower() not in TEXT_SUFFIXES:
        continue
    if path.resolve() == Path(__file__).resolve():
        continue
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    if re.search(r"(?<!_)\bpending\b(?!_)", text):
        bare_pending.append(str(path.relative_to(ROOT)))
assert not bare_pending, f"bare pending status found: {bare_pending}"

with (ROOT / "templates" / "plus_scenario_rules.csv").open("r", encoding="utf-8-sig", newline="") as stream:
    values = {row["status"] for row in csv.DictReader(stream)}
assert values <= ALLOWED, values

protocol = (ROOT / "interfaces" / "backend_protocol.md").read_text(encoding="utf-8")
for status in ALLOWED:
    assert f"`{status}`" in protocol, f"protocol omits {status}"
print("status vocabulary is consistent")
