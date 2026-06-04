"""trip-create / trip-update — top-level `note` support (HS 3339048660)."""
import pytest

import dc


def _parse_create(args):
    _pos, kw = dc._DCCore._parse_trip_create(args)
    return kw


def test_note_parsed_on_create():
    kw = _parse_create(["--start-date=2026-01-01", "--end-date=2026-01-02", "--place-id=p1", "--note=DCBKK week"])
    assert kw["note"] == "DCBKK week"


def test_create_without_note_is_backward_compatible():
    kw = _parse_create(["--start-date=2026-01-01", "--end-date=2026-01-02", "--place-id=p1"])
    assert "note" not in kw


def test_update_delegates_note_parsing():
    pos, kw = dc._DCCore._parse_trip_update(["t1", "--note=Updated caption"])
    assert pos == ("t1",)
    assert kw["note"] == "Updated caption"


def test_create_body_includes_note(core):
    core.create_trip(start_date="2026-01-01", end_date="2026-01-02", place_id="p1", note="DCBKK week")
    method, path, body = core.calls[-1]
    assert (method, path) == ("POST", "/trips")
    assert body["note"] == "DCBKK week"


def test_update_with_only_note(core):
    core.update_trip("t1", note="Updated caption")
    method, path, body = core.calls[-1]
    assert method == "PATCH"
    assert body == {"note": "Updated caption"}


def test_empty_update_still_rejected(core):
    with pytest.raises(dc.UsageError):
        core.update_trip("t1")


def test_both_trip_commands_expose_note(command_args):
    assert "note" in command_args("trip-create")
    assert "note" in command_args("trip-update")
