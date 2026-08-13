// static player-projection dataset backing the landing page's interactive sections.
// transcribed verbatim from Hashtag Basketball's 2025-26 per-game projections
// (see frontend/public/mockups/d-retrodata.html RAW array) — do not re-derive or round.

export interface PlayerRow {
  readonly rank: number;
  readonly name: string;
  readonly position: string;
  readonly team: string;
  readonly points: number;
  readonly rebounds: number;
  readonly assists: number;
  readonly steals: number;
  readonly blocks: number;
  readonly threes: number;
  // percentages are decimal fractions (e.g. 0.569), not 56.9 — downstream math/display assume fractions
  readonly fieldGoalPct: number;
  readonly fieldGoalAttempts: number;
  readonly freeThrowPct: number;
  readonly freeThrowAttempts: number;
  readonly turnovers: number;
}

export const SOURCE_NAME = "Hashtag Basketball";
export const SOURCE_URL =
  "https://hashtagbasketball.com/fantasy-basketball-projections";
// en dash (U+2013), not a hyphen — matches the mockup's rendered attribution copy
export const SOURCE_SEASON = "2025–26";

// [rank, name, position, team, points, rebounds, assists, steals, blocks, threes,
//  fieldGoalPct, fieldGoalAttempts, freeThrowPct, freeThrowAttempts, turnovers]
// rank 52 (Kadary Richmond) intentionally excluded: teamless small-sample artifact row.
type RawRow = [
  number,
  string,
  string,
  string,
  number,
  number,
  number,
  number,
  number,
  number,
  number,
  number,
  number,
  number,
  number,
];

const RAW: RawRow[] = [
  [1, "Nikola Jokic", "C", "DEN", 27.7, 12.9, 10.7, 1.4, 0.8, 1.7, 0.569, 17.4, 0.831, 7.4, 3.7],
  [2, "Victor Wembanyama", "PF", "SA", 25.0, 11.5, 3.1, 1.0, 3.1, 1.9, 0.512, 16.9, 0.827, 7.0, 2.4],
  [3, "Shai Gilgeous-Alexander", "PG", "OKC", 31.1, 4.3, 6.6, 1.4, 0.8, 1.7, 0.553, 19.4, 0.879, 9.0, 2.2],
  [4, "Tyrese Maxey", "PG", "PHI", 28.3, 4.1, 6.6, 1.9, 0.8, 3.1, 0.462, 21.4, 0.892, 5.9, 2.4],
  [5, "Luka Doncic", "PG", "LAL", 33.5, 7.7, 8.3, 1.6, 0.5, 4.0, 0.476, 22.8, 0.780, 10.1, 4.0],
  [6, "Kawhi Leonard", "SF", "LAC", 27.9, 6.3, 3.6, 1.8, 0.4, 2.7, 0.505, 19.4, 0.892, 6.4, 2.0],
  [7, "Donovan Mitchell", "PG", "CLE", 27.9, 4.5, 5.7, 1.5, 0.3, 3.2, 0.483, 20.1, 0.865, 6.1, 2.8],
  [8, "Stephen Curry", "PG", "GS", 26.6, 3.6, 4.7, 1.1, 0.4, 4.4, 0.468, 18.6, 0.923, 5.1, 2.8],
  [9, "Kevin Durant", "SG", "HOU", 26.0, 5.4, 4.8, 0.8, 0.9, 2.4, 0.521, 17.6, 0.874, 6.0, 3.2],
  [10, "Jamal Murray", "PG", "DEN", 25.4, 4.4, 7.1, 0.9, 0.4, 3.3, 0.483, 18.1, 0.887, 5.2, 2.3],
  [11, "Walker Kessler", "C", "UTA", 14.4, 10.8, 3.0, 1.4, 1.8, 1.2, 0.703, 7.4, 0.700, 4.0, 3.2],
  [12, "James Harden", "PG", "CLE", 23.6, 4.8, 8.0, 1.1, 0.4, 3.1, 0.434, 16.0, 0.884, 7.5, 3.5],
  [13, "Cade Cunningham", "PG", "DET", 23.9, 5.5, 9.9, 1.4, 0.8, 2.0, 0.461, 18.6, 0.812, 6.0, 3.7],
  [14, "Joel Embiid", "C", "PHI", 26.9, 7.7, 3.9, 0.6, 1.2, 1.4, 0.489, 18.3, 0.854, 8.8, 2.9],
  [15, "Anthony Edwards", "PG", "MIN", 28.8, 5.0, 3.7, 1.4, 0.8, 3.4, 0.489, 20.2, 0.796, 7.2, 2.8],
  [16, "Scottie Barnes", "SG", "TOR", 18.1, 7.5, 5.9, 1.4, 1.5, 0.9, 0.507, 14.0, 0.815, 3.7, 2.6],
  [17, "Lauri Markkanen", "SF", "UTA", 26.7, 6.9, 2.1, 1.0, 0.5, 2.7, 0.477, 19.2, 0.896, 6.4, 1.5],
  [18, "Giannis Antetokounmpo", "PF", "MIL", 27.6, 9.8, 5.4, 0.9, 0.7, 0.4, 0.624, 16.6, 0.650, 9.9, 3.2],
  [19, "Jalen Johnson", "SF", "ATL", 22.5, 10.3, 7.9, 1.2, 0.4, 1.7, 0.489, 17.1, 0.788, 5.3, 3.4],
  [20, "Kevin Porter Jr.", "PG", "MIL", 17.4, 5.2, 7.4, 2.2, 0.5, 1.2, 0.465, 13.5, 0.878, 4.1, 2.9],
  [21, "Austin Reaves", "PG", "LAL", 23.3, 4.7, 5.5, 1.1, 0.4, 2.3, 0.490, 14.9, 0.871, 7.3, 3.0],
  [22, "Trey Murphy III", "SG", "NO", 21.5, 5.7, 3.8, 1.5, 0.4, 3.2, 0.470, 15.9, 0.886, 3.7, 1.8],
  [23, "Karl-Anthony Towns", "PF", "NY", 20.1, 11.9, 3.0, 0.9, 0.5, 1.5, 0.501, 13.8, 0.858, 5.5, 2.5],
  [24, "Keyonte George", "PG", "UTA", 23.6, 3.7, 6.1, 1.1, 0.3, 2.5, 0.456, 16.3, 0.892, 7.0, 3.1],
  [25, "Chet Holmgren", "PF", "OKC", 17.1, 8.9, 1.7, 0.6, 1.9, 1.3, 0.558, 11.3, 0.792, 4.1, 1.6],
  [26, "Jimmy Butler III", "SG", "GS", 20.0, 5.6, 4.9, 1.4, 0.2, 0.8, 0.521, 12.1, 0.864, 7.6, 1.6],
  [27, "Anthony Davis", "PF", "WAS", 20.4, 11.1, 2.8, 1.1, 1.7, 0.5, 0.506, 16.7, 0.728, 4.1, 2.1],
  [28, "Michael Porter Jr.", "SF", "BKN", 24.2, 7.1, 3.0, 1.1, 0.2, 3.4, 0.463, 18.4, 0.860, 4.4, 2.3],
  [29, "Zach Edey", "C", "MEM", 13.6, 11.1, 1.1, 0.6, 1.9, 0.1, 0.633, 8.9, 0.781, 2.9, 2.4],
  [30, "Jayson Tatum", "SF", "BOS", 21.8, 10.0, 5.3, 1.4, 0.2, 2.9, 0.411, 17.9, 0.823, 4.9, 2.4],
  [31, "Nickeil Alexander-Walker", "PG", "ATL", 20.8, 3.4, 3.7, 1.3, 0.5, 3.2, 0.458, 15.3, 0.903, 3.9, 2.1],
  [32, "Devin Booker", "PG", "PHO", 26.1, 3.9, 6.0, 0.8, 0.3, 1.9, 0.456, 18.7, 0.873, 8.1, 3.2],
  [33, "Jaylen Brown", "SG", "BOS", 28.7, 6.9, 5.1, 1.0, 0.4, 2.0, 0.477, 21.7, 0.795, 7.5, 3.6],
  [34, "Amen Thompson", "PG", "HOU", 18.3, 7.8, 5.3, 1.5, 0.6, 0.3, 0.534, 13.2, 0.779, 4.9, 2.4],
  [35, "Deni Avdija", "SG", "POR", 24.2, 6.9, 6.7, 0.8, 0.6, 1.9, 0.462, 16.1, 0.802, 9.2, 3.8],
  [36, "Derrick White", "PG", "BOS", 16.5, 4.4, 5.4, 1.1, 1.3, 2.7, 0.394, 14.4, 0.902, 2.6, 1.7],
  [37, "Desmond Bane", "SG", "ORL", 20.1, 4.1, 4.1, 1.0, 0.5, 2.0, 0.483, 14.7, 0.908, 4.2, 2.0],
  [38, "Ty Jerome", "PG", "MEM", 19.7, 2.8, 5.7, 1.1, 0.3, 2.9, 0.477, 14.3, 0.875, 3.7, 1.8],
  [39, "LaMelo Ball", "PG", "CHA", 20.1, 4.8, 7.1, 1.2, 0.2, 3.8, 0.407, 17.3, 0.899, 2.5, 2.8],
  [40, "Alperen Sengün", "PF", "HOU", 20.4, 8.9, 6.2, 1.2, 1.1, 0.6, 0.519, 15.6, 0.691, 5.2, 3.2],
  [41, "Jalen Duren", "C", "DET", 19.5, 10.5, 2.0, 0.8, 0.8, 0.0, 0.650, 11.5, 0.747, 6.1, 1.9],
  [42, "Cooper Flagg", "PG", "DAL", 21.1, 6.7, 4.5, 1.2, 0.9, 1.0, 0.468, 17.1, 0.828, 4.9, 2.3],
  [43, "Evan Mobley", "PF", "CLE", 18.2, 9.0, 3.6, 0.7, 1.7, 1.0, 0.546, 13.2, 0.606, 4.6, 1.9],
  [44, "LeBron James", "SF", "LAL", 21.0, 6.1, 7.2, 1.2, 0.6, 1.3, 0.515, 15.3, 0.738, 5.3, 3.0],
  [45, "Jalen Brunson", "PG", "NY", 26.0, 3.3, 6.8, 0.8, 0.1, 2.6, 0.467, 19.9, 0.841, 5.7, 2.4],
  [46, "Josh Giddey", "PG", "CHI", 17.0, 8.3, 9.1, 1.0, 0.5, 1.9, 0.448, 13.3, 0.763, 4.2, 3.6],
  [47, "Dejounte Murray", "PG", "NO", 16.7, 5.4, 6.4, 1.6, 0.2, 1.4, 0.484, 13.0, 0.867, 3.2, 3.4],
  [48, "Tyler Herro", "PG", "MIA", 20.5, 4.8, 4.1, 0.7, 0.4, 2.6, 0.480, 15.6, 0.917, 3.3, 1.9],
  [49, "OG Anunoby", "SF", "NY", 16.7, 5.2, 2.2, 1.6, 0.7, 2.3, 0.484, 12.0, 0.828, 3.3, 1.8],
  [50, "Jaren Jackson Jr.", "PF", "UTA", 19.4, 5.7, 2.0, 1.1, 1.4, 1.8, 0.476, 15.0, 0.803, 4.2, 2.2],
  [51, "Brandon Miller", "SF", "CHA", 20.2, 4.9, 3.3, 1.0, 0.7, 3.1, 0.435, 16.1, 0.892, 3.4, 2.5],
  // rank 52 intentionally absent (see comment above)
  [53, "Ryan Rollins", "PG", "MIL", 17.3, 4.6, 5.6, 1.5, 0.4, 2.5, 0.472, 13.9, 0.796, 2.1, 2.7],
  [54, "Onyeka Okongwu", "PF", "ATL", 15.2, 7.6, 3.1, 1.1, 1.1, 2.0, 0.481, 11.6, 0.757, 2.7, 1.7],
  [55, "Jalen Suggs", "PG", "ORL", 13.8, 3.9, 5.5, 1.8, 0.7, 2.1, 0.435, 11.4, 0.855, 2.1, 2.7],
  [56, "Bam Adebayo", "PF", "MIA", 20.1, 10.0, 3.2, 1.2, 0.7, 1.7, 0.442, 15.7, 0.778, 5.8, 1.6],
  [57, "Donovan Clingan", "C", "POR", 12.1, 11.6, 2.1, 0.6, 1.7, 1.1, 0.520, 8.9, 0.680, 2.6, 1.2],
  [58, "Paul George", "SG", "PHI", 17.3, 5.3, 3.6, 1.6, 0.4, 2.7, 0.439, 13.9, 0.820, 3.0, 1.7],
  [59, "Alexandre Sarr", "C", "WAS", 16.3, 7.4, 2.7, 0.8, 2.0, 1.0, 0.482, 13.7, 0.688, 3.0, 1.7],
  [60, "Rudy Gobert", "C", "MIN", 10.9, 11.5, 1.7, 0.8, 1.6, 0.0, 0.682, 6.5, 0.526, 4.0, 1.4],
];

// readonly array of readonly rows: a downstream POOL.sort()/mutation would be a compile
// error instead of silently reordering this module-level singleton for every request/user
export const POOL: readonly PlayerRow[] = RAW.map(
  ([
    rank,
    name,
    position,
    team,
    points,
    rebounds,
    assists,
    steals,
    blocks,
    threes,
    fieldGoalPct,
    fieldGoalAttempts,
    freeThrowPct,
    freeThrowAttempts,
    turnovers,
  ]) => ({
    rank,
    name,
    position,
    team,
    points,
    rebounds,
    assists,
    steals,
    blocks,
    threes,
    fieldGoalPct,
    fieldGoalAttempts,
    freeThrowPct,
    freeThrowAttempts,
    turnovers,
  }),
);
