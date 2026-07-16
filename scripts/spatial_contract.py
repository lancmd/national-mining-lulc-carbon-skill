#!/usr/bin/env python3
"""Shared spatial-input rules used by project validation and workflow compilation."""

from __future__ import annotations

from typing import Any


DRIVER_TYPES = {"continuous", "categorical", "circular"}

# Distance, terrain, climate and socioeconomic surfaces are continuous.  A
# small explicit list avoids silently treating a thematic map as a float.
_CATEGORICAL_NAMES = {
    "soil", "soil_type", "geology", "lithology", "landform", "zoning",
    "protected_area", "administrative_zone", "ecological_redline",
}


def default_driver_type(name: str) -> str:
    normalised = name.strip().lower()
    if normalised == "aspect":
        return "circular"
    if normalised in _CATEGORICAL_NAMES or normalised.endswith("_class") or normalised.endswith("_type"):
        return "categorical"
    return "continuous"


def default_resampling(kind: str) -> str:
    return {"categorical": "majority", "continuous": "bilinear", "circular": "nearest"}[kind]


def parse_driver_factors(factors: Any) -> dict[str, dict[str, str]]:
    """Accept the legacy ``name: path`` form and the typed object form.

    Returned entries always contain ``path``, ``type`` and ``resampling``.
    Validation deliberately happens here so project validation and compiler
    cannot disagree on a factor's policy.
    """
    if not isinstance(factors, dict):
        raise ValueError("inputs.driver_factors must be an object")
    result: dict[str, dict[str, str]] = {}
    for raw_name, raw_value in factors.items():
        name = str(raw_name)
        if raw_value in (None, ""):
            continue
        if isinstance(raw_value, str):
            path, kind, resampling = raw_value, default_driver_type(name), None
        elif isinstance(raw_value, dict):
            path = raw_value.get("path")
            kind = str(raw_value.get("type") or default_driver_type(name)).lower()
            resampling = raw_value.get("resampling")
        else:
            raise ValueError(f"driver_factors.{name} must be a path or object")
        if not isinstance(path, str) or not path.strip():
            raise ValueError(f"driver_factors.{name}.path is required")
        if kind not in DRIVER_TYPES:
            raise ValueError(f"driver_factors.{name}.type must be one of {sorted(DRIVER_TYPES)}")
        policy = str(resampling or default_resampling(kind)).lower()
        allowed = {"categorical": {"majority", "nearest"}, "continuous": {"bilinear", "cubic"},
                   "circular": {"nearest"}}[kind]
        if policy not in allowed:
            raise ValueError(f"driver_factors.{name}.resampling={policy} is invalid for {kind}")
        result[name] = {"path": path, "type": kind, "resampling": policy}
    return result
