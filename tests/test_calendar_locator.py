"""calendar-update + locator-settings-update — closed-set toggle validation."""
import pytest

import dc


def _cal(args):
    _pos, kw = dc._DCCore._parse_calendar_patch(args)
    return kw["fields"]


def _loc(args):
    _pos, kw = dc._DCCore._parse_locator_settings_patch(args)
    return kw["fields"]


def test_calendar_valid_toggle():
    assert _cal(["--includeMyTickets=true"]) == {"includeMyTickets": True}


def test_calendar_unknown_toggle_rejected():
    with pytest.raises(dc.UsageError):
        _cal(["--includeBogus=true"])


def test_calendar_bad_bool_rejected():
    with pytest.raises(dc.UsageError):
        _cal(["--includeMyTrips=sometimes"])


def test_calendar_schema_matches_toggles(command_args):
    assert set(command_args("calendar-update")) == set(dc._DCCore._CALENDAR_TOGGLES)


def test_locator_valid_fields():
    assert _loc(["--enabled=true", "--trips=false"]) == {"enabled": True, "trips": False}


def test_locator_unknown_rejected():
    with pytest.raises(dc.UsageError):
        _loc(["--bogus=true"])


def test_locator_schema_complete(command_args):
    assert set(command_args("locator-settings-update")) == {"enabled", "events", "tickets", "trips"}
