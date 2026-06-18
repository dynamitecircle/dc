"""Pinned OpenAPI contract checks for the official clients.

The committed ``contracts/openapi.json`` snapshot is the release contract.
Tests should not fetch the live API; live drift is a release-time concern.
"""
import inspect
import json
from pathlib import Path

import dc


ROOT = Path(__file__).resolve().parents[1]
OPENAPI = json.loads((ROOT / "contracts" / "openapi.json").read_text())
OPERATION_MAP = json.loads((ROOT / "contracts" / "operation-map.json").read_text())
WRITE_METHODS = {"POST", "PATCH", "PUT", "DELETE"}


def _openapi_operations():
    operations = {}
    for path, item in OPENAPI["paths"].items():
        for method, operation in item.items():
            upper = method.upper()
            if upper not in {"GET", "POST", "PATCH", "PUT", "DELETE"}:
                continue
            operations[operation["operationId"]] = {
                "method": upper,
                "path": path,
            }
    return operations


def _registered_command_names():
    names = set()
    for _, fn in inspect.getmembers(dc.DC, predicate=inspect.isfunction):
        meta = getattr(fn, "_skill_command", None)
        if isinstance(meta, dict) and meta.get("name"):
            names.add(meta["name"])
    return names


def test_pinned_openapi_version_matches_python_client():
    assert OPENAPI["info"]["version"] == dc.DC_API_VERSION


def test_operation_map_covers_every_openapi_operation_once():
    openapi_ops = _openapi_operations()
    mapped = OPERATION_MAP["operations"]
    mapped_ids = [item["operationId"] for item in mapped]

    assert len(mapped_ids) == len(set(mapped_ids)), "duplicate operation-map entries"
    assert set(mapped_ids) == set(openapi_ops), (
        f"missing: {sorted(set(openapi_ops) - set(mapped_ids))}\n"
        f"extra: {sorted(set(mapped_ids) - set(openapi_ops))}"
    )

    for item in mapped:
        op = openapi_ops[item["operationId"]]
        assert item["method"] == op["method"], item["operationId"]
        assert item["path"] == op["path"], item["operationId"]


def test_operation_map_python_commands_exist():
    command_names = _registered_command_names()
    mapped = {item["pythonCommand"] for item in OPERATION_MAP["operations"]}
    assert mapped <= command_names, sorted(mapped - command_names)


def test_operation_map_write_classification_matches_python_annotations():
    for item in OPERATION_MAP["operations"]:
        should_write = item["method"] in WRITE_METHODS
        command = item["pythonCommand"]
        assert (command in dc._WRITE_COMMANDS) is should_write, (
            f"{item['operationId']} maps to {command}; "
            f"HTTP {item['method']} write={should_write}, "
            f"_WRITE_COMMANDS says {command in dc._WRITE_COMMANDS}"
        )
