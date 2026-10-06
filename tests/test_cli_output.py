"""The CLI output contract and exit codes (no network: HttpClient is stubbed).

- piped output stays plain JSON (no envelope), so existing scripts never break;
- `--count`, `--ids-only`, `--quiet` work on any list result;
- every error class has its own exit code.
"""
import json

import pytest

import dc


ROOMS = {"items": [{"roomID": "r1", "name": "SaaS", "type": "channel"},
                   {"roomID": "r2", "name": "AI", "type": "channel"}],
         "cursor": None}


@pytest.fixture
def stub(monkeypatch):
    """Route every GET to `responses[path-prefix]` (an API envelope or an exception)."""
    monkeypatch.setenv("DC_API_KEY", "dk_test")
    responses = {}

    def fake_get(url, headers=None):
        for prefix, value in responses.items():
            if prefix in url:
                if isinstance(value, Exception):
                    raise value
                return value
        return {"ok": True, "data": {}}

    monkeypatch.setattr(dc.HttpClient, "get", staticmethod(fake_get))
    return responses


def run(capsys, *argv):
    code = dc.DC().dispatch(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_piped_output_is_plain_json(stub, capsys):
    stub["/rooms"] = {"ok": True, "data": {"rooms": ROOMS["items"]}}
    code, out, _ = run(capsys, "rooms")
    assert code == 0
    data = json.loads(out)
    assert "ok" not in data and data["items"][0]["roomID"] == "r1"     # no envelope when piped


def test_count_and_ids_only(stub, capsys):
    stub["/rooms"] = {"ok": True, "data": {"rooms": ROOMS["items"]}}
    assert run(capsys, "rooms", "--count")[1].strip() == "2"
    assert run(capsys, "rooms", "--ids-only")[1].split() == ["r1", "r2"]


def test_count_on_a_non_list_is_a_usage_error(stub, capsys):
    stub["/profile"] = {"ok": True, "data": {"userID": "1", "displayName": "Simon"}}
    code, _, err = run(capsys, "profile", "--count")
    assert code == dc.EXIT_USAGE and "list" in err


def test_quiet_prints_nothing(stub, capsys):
    stub["/rooms"] = {"ok": True, "data": {"rooms": ROOMS["items"]}}
    code, out, err = run(capsys, "rooms", "-q")
    assert code == 0 and out == "" and err == ""


def test_table_lists_ids_names_types():
    text = dc.Runtime._table(ROOMS["items"])
    lines = text.splitlines()
    assert lines[0].split()[:3] == ["ID", "NAME", "TYPE"]
    assert "r1" in lines[1] and "SaaS" in lines[1] and "channel" in lines[1]


@pytest.mark.parametrize("error,expected", [
    ("unauthorized", dc.EXIT_AUTH),
    ("ticket_required", dc.EXIT_AUTH),
    ("profile_not_found", dc.EXIT_NOT_FOUND),
    ("rate_limited", dc.EXIT_RATE_LIMITED),
    ("validation_error", dc.EXIT_USAGE),
    ("server_error", dc.EXIT_ERROR),
])
def test_api_errors_map_to_exit_codes(stub, capsys, error, expected):
    stub["/profiles/"] = {"ok": False, "error": error, "message": "nope"}
    code, out, err = run(capsys, "dcer", "123")
    assert code == expected and error in err and out == ""


def test_network_error_exit_code(stub, capsys):
    stub["/profile"] = dc.NetworkError("Network error contacting x: refused")
    assert run(capsys, "profile")[0] == dc.EXIT_NETWORK


def test_missing_argument_is_a_usage_error_not_a_crash(stub, capsys):
    code, _, err = run(capsys, "dcer")
    assert code == dc.EXIT_USAGE and "user_id" in err


def test_missing_api_key_is_an_auth_error(monkeypatch, capsys):
    monkeypatch.delenv("DC_API_KEY", raising=False)
    monkeypatch.setattr(dc, "_load_dotenv", lambda *a, **k: None, raising=False)
    err = dc.DCError("Missing required environment variable: DC_API_KEY\nRun: …")
    assert dc.exit_code_for(err) == dc.EXIT_AUTH
