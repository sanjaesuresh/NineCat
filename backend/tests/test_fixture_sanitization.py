"""Guards against Yahoo fixtures ever committing real captured PII.

Recursively walks every fixtures/yahoo/*.json file and checks string values
against known leak patterns. This is the proof that fixture sanitization
actually happened, not an eyeball check -- a regression here means a future
re-record slipped real data into a committed fixture.
"""

import json
import re
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "yahoo"

# real Yahoo GUIDs are 26 uppercase-alnum characters; anything matching this
# shape anywhere in a committed fixture is almost certainly a live-captured value
_REAL_GUID_RE = re.compile(r"^[A-Z0-9]{26}$")

# fixtures actually re-recorded from a live account capture (2026-09-13, see
# README.md) are held to the strict "guid must say SANITIZED" bar; the older
# hand-built fixtures (league_teams.json etc, deliberately not re-recorded --
# their meaningful re-record needs post-draft data) use short synthetic
# placeholders like "GUID1" that were never real data, so are out of scope here
_LIVE_RECORDED_FIXTURES = {
    "user_teams.json",
    "user_leagues.json",
    "league_settings.json",
    "league_standings_preseason.json",
}


def _iter_string_values(node):
    """Yield (key, value) for every string leaf anywhere in a JSON tree.

    key is None for a string found directly inside a list (no dict key to
    report), which is fine -- the value itself is what these checks care about.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, str):
                yield key, value
            elif isinstance(value, (dict, list)):
                yield from _iter_string_values(value)
    elif isinstance(node, list):
        for item in node:
            if isinstance(item, str):
                yield None, item
            elif isinstance(item, (dict, list)):
                yield from _iter_string_values(item)


def _fixture_files() -> list[Path]:
    return sorted(FIXTURE_DIR.glob("*.json"))


def _load_all() -> list[tuple[Path, dict]]:
    return [(path, json.loads(path.read_text())) for path in _fixture_files()]


def test_fixtures_directory_is_not_empty():
    # a silently-empty glob would make every check below vacuously pass
    assert _fixture_files()


def test_guid_values_are_sanitized_in_live_recorded_fixtures():
    for path, data in _load_all():
        if path.name not in _LIVE_RECORDED_FIXTURES:
            continue
        for key, value in _iter_string_values(data):
            if key == "guid":
                assert value.startswith("SANITIZED"), f"{path.name}: unsanitized guid {value!r}"


def test_no_real_email_addresses():
    for path, data in _load_all():
        for _key, value in _iter_string_values(data):
            if "@" in value:
                assert value.endswith("example.test") or value.endswith(
                    "example.invalid"
                ), f"{path.name}: possible real email address {value!r}"


def test_password_fields_are_empty():
    for path, data in _load_all():
        for key, value in _iter_string_values(data):
            if key == "password":
                assert value == "", f"{path.name}: non-empty password field"


def test_no_yahoo_invitation_urls():
    for path, data in _load_all():
        for _key, value in _iter_string_values(data):
            is_invitation_link = "invitation" in value and "yahoo.com" in value
            assert not is_invitation_link, f"{path.name}: yahoo invitation url leaked {value!r}"


def test_no_real_yahoo_guid_shaped_values_anywhere():
    for path, data in _load_all():
        for _key, value in _iter_string_values(data):
            assert not _REAL_GUID_RE.match(value), f"{path.name}: guid-shaped value {value!r}"
