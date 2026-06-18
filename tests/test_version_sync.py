"""Guard against version drift across the repo.

``DC_API_VERSION`` in ``py/dc.py`` is the Python source of truth — the wheel
reads it dynamically at build time (see ``pyproject.toml`` ``[tool.hatch.version]``).
The official clients and pinned contract are released together, so these files
must all carry the same API contract version:

- ``manifest.json`` — the MCPB manifest ``version`` field
- ``py/config.json`` — the skill metadata ``version`` field
- ``server.json`` — the MCP Registry metadata ``version`` field
- ``contracts/openapi.json`` — pinned API contract ``info.version``
- ``ts/package.json`` — npm package ``version``
- ``ts/src/version.ts`` — exported TypeScript ``DC_API_VERSION``

Most are not wired to the constant, so bumping ``DC_API_VERSION`` without
updating them would ship mismatched metadata. This test fails the build in
that case.
"""
import json
import os
import re

import dc  # noqa: E402  (sys.path is set up by conftest.py)

_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _read_json_version(*relative_path):
    with open(os.path.join(_REPO_ROOT, *relative_path), encoding="utf-8") as fh:
        return json.load(fh)["version"]


def _read_openapi_version():
    with open(os.path.join(_REPO_ROOT, "contracts", "openapi.json"), encoding="utf-8") as fh:
        return json.load(fh)["info"]["version"]


def _read_ts_exported_version():
    with open(os.path.join(_REPO_ROOT, "ts", "src", "version.ts"), encoding="utf-8") as fh:
        text = fh.read()
    match = re.search(r'DC_API_VERSION\s*=\s*"([^"]+)"', text)
    assert match, "Could not find DC_API_VERSION in ts/src/version.ts"
    return match.group(1)


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


def test_pinned_openapi_version_matches_constant():
    openapi = _read_openapi_version()
    assert openapi == dc.DC_API_VERSION, (
        f"contracts/openapi.json version {openapi!r} != DC_API_VERSION {dc.DC_API_VERSION!r}. "
        "Update the pinned OpenAPI contract to match py/dc.py."
    )


def test_typescript_package_version_matches_constant():
    package = _read_json_version("ts", "package.json")
    assert package == dc.DC_API_VERSION, (
        f"ts/package.json version {package!r} != DC_API_VERSION {dc.DC_API_VERSION!r}. "
        "Bump the npm package version with the API contract."
    )


def test_typescript_exported_version_matches_constant():
    ts_version = _read_ts_exported_version()
    assert ts_version == dc.DC_API_VERSION, (
        f"ts/src/version.ts DC_API_VERSION {ts_version!r} != Python DC_API_VERSION {dc.DC_API_VERSION!r}. "
        "Keep the Python and TypeScript clients on the same API contract version."
    )
