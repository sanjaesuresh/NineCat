# NineCat

NineCat is a fantasy basketball analytics web app for Yahoo Fantasy head-to-head 9-category leagues. It signs users in with their Yahoo account, syncs their league (settings, teams, standings, rosters), and builds a deterministic per-category "build profile" (strong / average / punt) across the nine scoring categories — FG%, FT%, 3PM, PTS, REB, AST, ST, BLK, TO — backed by an NBA schedule and player-stats warehouse. Draft, matchup, waiver, and trade tools layer on top of this foundation. All Yahoo access is read-only: NineCat recommends, it never acts on your team.

Every recommendation you see is arithmetic. An optional Claude advisor can add written reasoning on top of it — see [Claude advisor](#claude-advisor) — but the engine decides what is on the list, and the advisor only ever reorders within that list and explains it. Without an API key configured, every feature works exactly as it always did and says plainly that explanations are off.

## Features

- Yahoo Fantasy Basketball league integration
- 9-category team and build analysis
- Draft, matchup, waiver, and trade tools
- Player projections and NBA schedule data
- Data-driven roster recommendations
- Optional AI-powered explanations through Claude

## Layout
