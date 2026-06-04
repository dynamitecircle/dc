"""profile-update — explicit, validated field map (fixes the strict-schema 400s)."""
import pytest

import dc


def _fields(args):
    _pos, kw = dc._DCCore._parse_profile_patch(args)
    return kw["fields"]


def test_correct_api_field_names():
    assert _fields(["--bizDesc=We build things", "--headline=CEO"]) == {
        "bizDesc":  "We build things",
        "headline": "CEO",
    }


def test_legacy_aliases_resolve_to_real_fields():
    # These three names were historically documented but 400 against the
    # strict server schema. They must now map to the real fields.
    assert _fields(["--businessDescription=x", "--businessUrl=https://a.com", "--industry=Software"]) == {
        "bizDesc":     "x",
        "bizWeb":      "https://a.com",
        "bizIndustry": "Software",
    }


def test_unknown_field_is_rejected():
    with pytest.raises(dc.UsageError):
        _fields(["--notARealField=x"])


def test_boolean_fields_coerced():
    assert _fields(["--connectIsPrivate=true", "--bizRevenueIsPrivate=false"]) == {
        "connectIsPrivate":    True,
        "bizRevenueIsPrivate": False,
    }


def test_bad_boolean_value_rejected():
    with pytest.raises(dc.UsageError):
        _fields(["--connectIsPrivate=maybe"])


def test_every_declared_field_is_accepted():
    for name in dc._DCCore._PROFILE_FIELDS:
        value = "true" if name in dc._DCCore._PROFILE_BOOL_FIELDS else "x"
        assert name in _fields([f"--{name}={value}"])


def test_mcp_schema_matches_parser_field_set(command_args):
    # The guard that would have caught `businessDescription`: the MCP schema
    # must expose exactly the fields the parser accepts — no more, no less.
    assert set(command_args("profile-update")) == set(dc._DCCore._PROFILE_FIELDS)


def test_no_catch_all_accept_extras(command_args):
    assert "_accept_extras" not in command_args("profile-update")
