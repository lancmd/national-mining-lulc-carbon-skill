"""Keep source, package, licence and change records aligned for a release."""

from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
package = tomllib.loads((ROOT / "mcp_server" / "pyproject.toml").read_text(encoding="utf-8"))
assert version == package["project"]["version"] == "0.2.0"
assert "MIT License" in (ROOT / "LICENSE").read_text(encoding="utf-8")
assert version in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
print('{"status":"completed","checks":["version","license","changelog"]}')
