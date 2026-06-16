"""Guard against version drift across the repo.

``DC_API_VERSION`` in ``py/dc.py`` is the single source of truth — the wheel
reads it dynamically at build time (see ``pyproject.toml`` ``[tool.hatch.version]``).
Two other files carry a hand-maintained copy of the same version:

- ``manifest.json`` — the MCPB manifest ``version`` field
- ``py/config.json`` — the skill metadata ``version`` field
- ``server.json`` — the MCP Registry metadata ``version`` field

Neither is wired to the constant, so bumping ``DC_API_VERSION`` without
updating them would ship a mismatched manifest / metadata. This test fails
the build in that case, forcing all three to stay in lockstep.
"""
import json
import os
import re

import dc  # noqa: E402  (sys.path is set up by conftest.py)

_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _read_json_version(*relative_path):
    with open(os.path.join(_REPO_ROOT, *relative_path), encoding="utf-8") as fh:
        return json.load(fh)["version"]


def test_dc_api_version_is_a_valid_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", dc.DC_API_VERSION), dc.DC_API_VERSION


def test_manifest_version_matches_constant():
    manifest = _read_json_version("manifest.json")
    assert manifest == dc.DC_API_VERSION, (
        f"manifest.json version {manifest!r} != DC_API_VERSION {dc.DC_API_VERSION!r}. "
        "Bump manifest.json to match py/dc.py."
    )


def test_config_version_matches_constant():
    config = _read_json_version("py", "config.json")
    assert config == dc.DC_API_VERSION, (
        f"py/config.json version {config!r} != DC_API_VERSION {dc.DC_API_VERSION!r}. "
        "Bump py/config.json to match py/dc.py."
    )


def test_server_json_version_matches_constant():
    server = _read_json_version("server.json")
    assert server == dc.DC_API_VERSION, (
        f"server.json version {server!r} != DC_API_VERSION {dc.DC_API_VERSION!r}. "
        "Bump server.json to match py/dc.py."
    )
