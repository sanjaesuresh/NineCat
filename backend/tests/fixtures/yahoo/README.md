# Yahoo fixtures

These JSON files are **hand-built** from Yahoo Fantasy Sports API's documented
`?format=json` response shapes (readthedocs / wrapper library docs), not
recorded from a live account — real access hasn't been verified yet. They
model a realistic NBA 9-cat head-to-head league so `parsers.py` has something
concrete to unwrap.

Each file must be **re-recorded from a real account** once live Yahoo API
access is verified, via `YahooGateway.record_fixture(resource_path, dest_dir)`
(see `backend/src/ninecat/yahoo/gateway.py`). Re-recording may reveal shape
details Yahoo's docs don't fully specify (e.g. exact key ordering, optional
fields Yahoo omits vs. nulls) — `parsers.py`'s tests should be re-run and
adjusted against the real payloads at that point.

| File | Resource path it stands in for | Used by |
|---|---|---|
| `user_leagues.json` | `users;use_login=1/games;game_keys=nba/leagues` | `get_user_leagues` |
| `league_settings.json` | `league/{league_key}/settings` | `get_league_settings` |
| `league_teams.json` | `league/{league_key}/teams` | `get_league_teams` |
| `team_roster.json` | `team/{team_key}/roster` | `get_team_roster` |
| `league_standings.json` | `league/{league_key}/standings` | `get_standings` |
| `league_scoreboard.json` | `league/{league_key}/scoreboard;week={week}` | `get_scoreboard` |
| `league_scoreboard_current_week.json` | `league/{league_key}/scoreboard` (no `;week=`) | `get_scoreboard` with `week=None` |
| `user_teams.json` | `users;use_login=1/games;game_keys=nba/teams` | `get_user_teams` |
| `malformed_league_settings.json` | n/a — deliberately missing `stat_categories`/`scoring_type`/playoff keys, used only to test `YahooParseError` | error-path test |
