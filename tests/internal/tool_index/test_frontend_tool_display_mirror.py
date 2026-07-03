"""
Tool Display Metadata Drift Test — FOUNDATION-RETOUCH-002-AI1-FIX1

Enforces parity between:
- Canonical source: system/tool_index/tools.json  (backend)
- Frontend mirror: ai_lab_gui/frontend/src/constants/toolDisplayMetadata.js

This test is intentionally scoped to the current static mirror format.
If toolDisplayMetadata.js changes structure significantly, this test must be updated.
"""

import json
import os
import re

import pytest


# Resolve project root (this file lives at tests/internal/tool_index/)
_PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)

_TOOLS_JSON_PATH = os.path.join(_PROJECT_ROOT, "system", "tool_index", "tools.json")
_FRONTEND_MIRROR_PATH = os.path.join(
    _PROJECT_ROOT,
    "ai_lab_gui",
    "frontend",
    "src",
    "constants",
    "toolDisplayMetadata.js",
)

# Regex to extract entries from the static JS object literal.
# Matches lines like:   tool_name: { label: "Some label", category: "some_cat" },
_ENTRY_RE = re.compile(
    r"^\s+(\w+):\s*\{\s*label:\s*\"([^\"]+)\",\s*category:\s*\"([^\"]+)\"\s*\},?\s*$",
    re.MULTILINE,
)


def _load_tools_json_ui_display():
    """Load canonical ui_display metadata from tools.json for production tools."""
    with open(_TOOLS_JSON_PATH, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    canonical = {}
    for tool_name, tool_data in manifest.items():
        if not tool_data.get("production", False):
            continue
        ui_display = tool_data.get("ui_display")
        if ui_display is not None:
            canonical[tool_name] = {
                "label": ui_display.get("label"),
                "category": ui_display.get("category"),
            }
    return canonical


def _load_frontend_mirror():
    """Parse the frontend static mirror JS file and extract display metadata."""
    with open(_FRONTEND_MIRROR_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    # Locate the _TOOL_DISPLAY_MAP object body
    start_marker = "const _TOOL_DISPLAY_MAP = {"
    start_idx = content.find(start_marker)
    if start_idx == -1:
        pytest.fail(
            f"Could not find '{start_marker}' in {_FRONTEND_MIRROR_PATH}. "
            "Mirror format may have changed."
        )

    # Find the opening brace of the object (the { inside the start marker)
    brace_start = content.find("{", start_idx)
    if brace_start == -1:
        pytest.fail("Could not find opening brace of _TOOL_DISPLAY_MAP.")

    brace_depth = 1
    pos = brace_start + 1
    while pos < len(content) and brace_depth > 0:
        ch = content[pos]
        if ch == "{":
            brace_depth += 1
        elif ch == "}":
            brace_depth -= 1
        pos += 1

    if brace_depth != 0:
        pytest.fail("Unbalanced braces in _TOOL_DISPLAY_MAP — mirror format may have changed.")

    body = content[brace_start:pos]

    mirror = {}
    for match in _ENTRY_RE.finditer(body):
        tool_name = match.group(1)
        label = match.group(2)
        category = match.group(3)
        mirror[tool_name] = {"label": label, "category": category}

    return mirror


class TestToolDisplayMirrorParity:
    """Enforce parity between tools.json ui_display and frontend static mirror."""

    def test_no_drift_between_tools_json_and_frontend_mirror(self):
        """
        Assert that every production tool with ui_display in tools.json
        has an identical entry in toolDisplayMetadata.js, and vice versa.
        """
        canonical = _load_tools_json_ui_display()
        mirror = _load_frontend_mirror()

        canonical_keys = set(canonical.keys())
        mirror_keys = set(mirror.keys())

        # 1. Missing in mirror
        missing_in_mirror = canonical_keys - mirror_keys
        if missing_in_mirror:
            details = ", ".join(sorted(missing_in_mirror))
            pytest.fail(
                f"Production tools with ui_display missing from frontend mirror: {details}. "
                f"Update ai_lab_gui/frontend/src/constants/toolDisplayMetadata.js to match system/tool_index/tools.json"
            )

        # 2. Extra in mirror
        extra_in_mirror = mirror_keys - canonical_keys
        if extra_in_mirror:
            details = ", ".join(sorted(extra_in_mirror))
            pytest.fail(
                f"Frontend mirror contains tools not in tools.json production ui_display set: {details}. "
                f"Remove from ai_lab_gui/frontend/src/constants/toolDisplayMetadata.js or add to system/tool_index/tools.json"
            )

        # 3. Label / category mismatches
        mismatches = []
        for tool_name in canonical_keys:
            can = canonical[tool_name]
            mir = mirror[tool_name]
            if can["label"] != mir["label"]:
                mismatches.append(
                    f"{tool_name}: label mismatch "
                    f"(tools.json='{can['label']}', mirror='{mir['label']}')"
                )
            if can["category"] != mir["category"]:
                mismatches.append(
                    f"{tool_name}: category mismatch "
                    f"(tools.json='{can['category']}', mirror='{mir['category']}')"
                )

        if mismatches:
            detail = "; ".join(mismatches)
            pytest.fail(
                f"ui_display drift detected: {detail}. "
                f"Update ai_lab_gui/frontend/src/constants/toolDisplayMetadata.js to match system/tool_index/tools.json"
            )
