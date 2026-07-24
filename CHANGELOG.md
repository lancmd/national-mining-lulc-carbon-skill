# Changelog

This record tracks user-visible changes to MAESA-Agent. Dates refer to source releases, not to individual research runs.

## 0.2.0 — 2026-07-24

- Project construction now runs the full local-project validator and returns its report with the build response.
- `pending_validation` from an analysis command now pauses the workflow and survives to the final job state.
- The shipped PyTorch configuration follows the runtime input contract; the registered ResNet-50 package is pinned to its reviewed SHA-256 fingerprint.
- InVEST-only projects can select Annual Water Yield, Habitat Quality, or other supported models without silently enabling Carbon.
- ArcGIS layout composition recognises common Chinese element names, and discrete class-code checks compare whole values.
- Copilot plans include nested input paths and configured validation evidence/report paths.
- Added portable contract tests and an opt-in local real ResNet-50 inference test.

## 0.1.0 — 2026-07-20

- Initial local-first MCP workflow for classification, PLUS, InVEST, ecosystem service evaluation, and ArcGIS Pro output.
