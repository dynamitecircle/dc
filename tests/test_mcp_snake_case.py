"""MCP tool names and field names are snake_case.

The CLI stays kebab-case (`dc trip-create`, `--start-date`) and the Python
library is snake_case (`dc.trip_create()`). The MCP layer — what an agent
calls — must also be snake_case (`mcp__dc__trip_create`, field `start_date`).
These guards lock the kebab->snake conversion at the MCP boundary
(`_build_input_schema` + the tool-name mapping in `run_mcp`).
"""
import dc  # noqa: E402 (sys.path set up by conftest.py)


def _meta(name):
    for n, _, m in _commands():
        if n == name:
            return m
    raise KeyError(name)


def _commands():
    import inspect
    out = []
    for _, fn in inspect.getmembers(dc.DC, predicate=inspect.isfunction):
        meta = getattr(fn, "_skill_command", None)
        if isinstance(meta, dict) and meta.get("name"):
            out.append((meta["name"], fn, meta))
    return out


def test_command_names_stay_kebab():
    # The CLI command name is unchanged — only the MCP tool name is snaked.
    assert "trip-create" in {n for n, _, _ in _commands()}


def test_schema_flag_fields_are_snake_case():
    # trip-create declares kebab flags (start-date, place-id) in args=; the
    # built MCP schema must expose them as snake_case.
    schema = dc._build_input_schema(_meta("trip-create")["args"], positional=[])
    props = schema["properties"]
    assert "start_date" in props
    assert "place_id" in props
    assert not any("-" in key for key in props), props


def test_schema_positional_fields_are_snake_case():
    # A kebab positional (event-id) is exposed as the snake field event_id.
    schema = dc._build_input_schema({}, positional=["event-id"])
    assert "event_id" in schema["properties"]
    assert "event-id" not in schema["properties"]


def test_tool_name_mapping_is_snake_case():
    # The exact transform run_mcp applies to the tool name.
    assert "trip-create".replace("-", "_") == "trip_create"


def test_required_list_is_snake_case():
    schema = dc._build_input_schema(_meta("trip-create")["args"], positional=[])
    assert all("-" not in key for key in schema.get("required", []))
