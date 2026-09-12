# Yahoo fixtures

Two provenances live side by side in this directory now that real Yahoo API
access has been verified:

- **Live-recorded (2026-09-13), sanitized**: `user_teams.json`,
  `user_leagues.json`, `league_settings.json`, `league_standings_preseason.json`.
  Captured from a real (pre-draft, 1-team) NBA league via
  `YahooGateway.record_fixture(resource_path, dest_dir)` (see
  `backend/src/ninecat/yahoo/gateway.py`), then sanitized: `guid` ->
  `"SANITIZEDGUID1"`, league ids `25328`/`29586` -> `11111`/`22222`, league
  names -> `"Sample League A"`/`"Sample League B"`, team names -> `"Team
  Alpha"`/`"Team Beta"`, manager nickname -> `"Manager A"`, email ->
  `"sanitized@example.test"`, `password`/`iris_group_chat_id`/
  `short_invitation_url`/`sendbird_channel_url` -> `""`, logo/avatar urls ->
  `"https://example.test/logo.png"`. `tests/test_fixture_sanitization.py`
  guards this recursively so a future re-record can't silently reintroduce
  real data. These fixtures pin real-Yahoo structural quirks the old
  hand-built versions didn't have: empty-list padding inside team attr
  arrays (`_merge_attrs` tolerates it), string vs. int stat ids, and a
  pre-season `rank: ""` / `percentage: ""` shape (`parse_standings` maps rank
  `""` to `0`).

- **Still hand-built** from Yahoo's documented `?format=json` shapes
  (readthedocs / wrapper library docs), not yet re-recorded:
  `league_teams.json`, `team_roster.json`, `league_scoreboard.json`,
  `league_scoreboard_current_week.json`, `malformed_league_settings.json`,
  `league_draftresults.json`, `league_draftresults_predraft.json`. Deferred
  deliberately: a meaningful re-record of these needs a league that has
  actually drafted (rosters, a live scoreboard week, draft results), and the
  captured account is still pre-draft. `league_standings.json` (the
  multi-team, mid-season shape) is also kept hand-built on purpose --
  the real capture is a 1-team pre-season league and would gut its
  order-preservation/multi-team assertions, so it lives alongside
  `league_standings_preseason.json` rather than replacing it.

| File | Resource path it stands in for | Used by |
|---|---|---|
| `user_leagues.json` | `users;use_login=1/games;game_keys=nba/leagues` | `get_user_leagues` |
| `league_settings.json` | `league/{league_key}/settings` | `get_league_settings` |
| `league_teams.json` | `league/{league_key}/teams` | `get_league_teams` |
| `team_roster.json` | `team/{team_key}/roster` | `get_team_roster` |
| `league_standings.json` | `league/{league_key}/standings` (multi-team, mid-season) | `get_standings` |
| `league_standings_preseason.json` | `league/{league_key}/standings` (1-team, pre-season, `rank: ""`) | `get_standings` |
| `league_scoreboard.json` | `league/{league_key}/scoreboard;week={week}` | `get_scoreboard` |
| `league_scoreboard_current_week.json` | `league/{league_key}/scoreboard` (no `;week=`) | `get_scoreboard` with `week=None` |
| `user_teams.json` | `users;use_login=1/games;game_keys=nba/teams` | `get_user_teams` |
| `malformed_league_settings.json` | n/a — deliberately missing `stat_categories`/`scoring_type`/playoff keys, used only to test `YahooParseError` | error-path test |
| `league_draftresults.json` | `league/{league_key}/draftresults` | `get_draft_results` |
| `league_draftresults_predraft.json` | `league/{league_key}/draftresults` (draft not yet started) | `get_draft_results` |
