import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { fixturePlayers } from "./components/__fixtures__/players";

const dataset = {
  season: "2026-27",
  projection_date: "2026-08-01",
  last_updated: "2026-08-01T00:00:00Z",
  schedule_available: true,
  candidate_windows: ["17-19", "18-20", "19-21", "20-22", "21-23", "22-24"],
  default_window: "19-21",
  // composite_weights/value_split filled in (Task 18's Settings tab reads
  // them); everything else Settings.tsx doesn't touch stays absent as before
  settings: {
    composite_weights: {
      per_game: 0.4,
      availability_adjusted: 0.2,
      expected_games: 0.1,
      role_usage: 0.1,
      playoff_schedule: 0.05,
      consensus: 0.05,
      team_environment: 0.05,
      category_scarcity: 0.05,
    },
    value_split: { regular_season: 0.7, playoff: 0.3 },
  },
  players: fixturePlayers,
};

describe("App", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the partial-schedule notice (not the plain unavailable one) when playoff_window_force_unavailable is true", async () => {
    const partialDataset = {
      ...dataset,
      schedule_available: false,
      playoff_window_force_unavailable: true,
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify(partialDataset), { status: 200 })),
    );

    render(<App />);
    await waitFor(() => expect(screen.getByText("Ace Guard")).toBeInTheDocument());

    expect(screen.getByText(/Partial schedule published/)).toBeInTheDocument();
    expect(screen.queryByText(/Playoff schedule data isn't available yet/)).not.toBeInTheDocument();
  });

  it("shows the plain unavailable notice when the schedule never fetched at all", async () => {
    const unavailableDataset = {
      ...dataset,
      schedule_available: false,
      playoff_window_force_unavailable: false,
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify(unavailableDataset), { status: 200 })),
    );

    render(<App />);
    await waitFor(() => expect(screen.getByText("Ace Guard")).toBeInTheDocument());

    expect(screen.getByText(/Playoff schedule data isn't available yet/)).toBeInTheDocument();
    expect(screen.queryByText(/Partial schedule published/)).not.toBeInTheDocument();
  });

  it("renders the table once the dataset loads, and shows an empty state with a working clear button on an impossible filter", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify(dataset), { status: 200 })),
    );

    render(<App />);

    await waitFor(() => expect(screen.getByText("Ace Guard")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("Search"), { target: { value: "no such player" } });

    expect(await screen.findByText("No players match the current filters.")).toBeInTheDocument();
    expect(screen.getByText(`0 of ${fixturePlayers.length} players`)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(await screen.findByText("Ace Guard")).toBeInTheDocument();
  });

  it("selecting a row opens the real player detail panel (Task 17 replaced the placeholder)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify(dataset), { status: 200 })),
    );

    render(<App />);
    await waitFor(() => expect(screen.getByText("Ace Guard")).toBeInTheDocument());

    fireEvent.click(screen.getByText("Ace Guard"));

    expect(screen.getByRole("heading", { name: "Ace Guard" })).toBeInTheDocument();
    // a section only the real detail panel renders, not the old placeholder
    expect(screen.getByText("Why ranked here")).toBeInTheDocument();
  });

  it("stacks the detail panel below the table on narrow viewports instead of forcing horizontal overflow", async () => {
    // jsdom can't measure actual layout/overflow, so this pins the
    // responsive classes directly: at 360px (below the lg breakpoint) the
    // aside must be full-width and the row container must be column-stacked,
    // not a fixed w-80 sibling of a no-wrap flex row (that combination is
    // what caused the page-level horizontal overflow this test guards).
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify(dataset), { status: 200 })),
    );

    render(<App />);
    await waitFor(() => expect(screen.getByText("Ace Guard")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Ace Guard"));

    const aside = screen.getByRole("complementary");
    expect(aside).toHaveClass("w-full", "lg:w-80", "lg:shrink-0");
    expect(aside.className).not.toMatch(/(^|\s)shrink-0(\s|$)/); // unconditional shrink-0 regressed this once

    const row = aside.parentElement;
    expect(row).not.toBeNull();
    expect(row).toHaveClass("flex-col", "lg:flex-row");
    expect(row?.className).not.toMatch(/(^|\s)flex-row(\s|$)/); // unconditional flex-row (no wrap) is the other half of the bug
  });

  it("returns focus to the triggering row when the panel is closed with Escape", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify(dataset), { status: 200 })),
    );

    render(<App />);
    await waitFor(() => expect(screen.getByText("Ace Guard")).toBeInTheDocument());

    // fireEvent.click doesn't move focus in jsdom the way a real click does,
    // so drive selection via keyboard to get PlayerDetail's
    // previouslyFocused ref to actually capture this row
    const rankingsRow = within(screen.getByRole("table")).getAllByRole("row")[1]; // [0] is the header row
    rankingsRow.focus();
    fireEvent.keyDown(rankingsRow, { key: "Enter" });

    expect(screen.getByRole("heading", { name: "Ace Guard" })).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("heading", { name: "Ace Guard" })).not.toBeInTheDocument());
    expect(document.activeElement).toBe(rankingsRow);
  });

  it("returns focus to the triggering row when the panel is closed via the close button", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify(dataset), { status: 200 })),
    );

    render(<App />);
    await waitFor(() => expect(screen.getByText("Ace Guard")).toBeInTheDocument());

    const rankingsRow = within(screen.getByRole("table")).getAllByRole("row")[1];
    rankingsRow.focus();
    fireEvent.keyDown(rankingsRow, { key: "Enter" });

    fireEvent.click(screen.getByRole("button", { name: "Close Ace Guard detail" }));

    await waitFor(() => expect(screen.queryByRole("heading", { name: "Ace Guard" })).not.toBeInTheDocument());
    expect(document.activeElement).toBe(rankingsRow);
  });

  it("tab switching renders each page and marks the active tab with aria-current", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify(dataset), { status: 200 })),
    );

    render(<App />);
    await waitFor(() => expect(screen.getByText("Ace Guard")).toBeInTheDocument());

    const rankingsTab = screen.getByRole("button", { name: "Rankings" });
    const moversTab = screen.getByRole("button", { name: "Movers" });
    const settingsTab = screen.getByRole("button", { name: "Settings" });
    expect(rankingsTab).toHaveAttribute("aria-current", "page");

    fireEvent.click(moversTab);
    expect(moversTab).toHaveAttribute("aria-current", "page");
    expect(rankingsTab).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("heading", { name: "Model Fallers" })).toBeInTheDocument();

    fireEvent.click(settingsTab);
    expect(settingsTab).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("heading", { name: "Composite weights" })).toBeInTheDocument();

    fireEvent.click(rankingsTab);
    expect(screen.getByRole("table")).toBeInTheDocument();
  });

  it("preserves the selected player's detail panel when switching tabs and back", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify(dataset), { status: 200 })),
    );

    render(<App />);
    await waitFor(() => expect(screen.getByText("Ace Guard")).toBeInTheDocument());

    fireEvent.click(screen.getByText("Ace Guard"));
    expect(screen.getByRole("heading", { name: "Ace Guard" })).toBeInTheDocument();

    // switching to Movers keeps the same shared selection -- the detail panel
    // stays open there too, not just re-appearing back on Rankings
    fireEvent.click(screen.getByRole("button", { name: "Movers" }));
    expect(screen.getByRole("heading", { name: "Ace Guard" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Rankings" }));
    expect(screen.getByRole("heading", { name: "Ace Guard" })).toBeInTheDocument();
  });

  it("switching the playoff-window dropdown re-ranks the table and shows the recompute note, then reverts to the shipped order exactly", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify(dataset), { status: 200 })),
    );

    render(<App />);
    await waitFor(() => expect(screen.getByText("Ace Guard")).toBeInTheDocument());

    // shipped default: Ace Guard (final_rank 1) leads, no recompute note
    const rowsBefore = within(screen.getByRole("table")).getAllByRole("row").slice(1);
    expect(within(rowsBefore[0]).getByText("Ace Guard")).toBeInTheDocument();
    expect(screen.queryByText(/ranking recomputed for weeks/)).not.toBeInTheDocument();

    // only "Detail Rich" has a schedule.windows["18-20"] entry (0.4 z); every
    // other fixture player has no windows map at all, so their swapped
    // playoff_schedule component goes null and their score stays 0 -- Detail
    // Rich's single nonzero component (0.05 weight * 0.4 z = 0.02) wins #1
    fireEvent.change(screen.getByLabelText("Playoff weeks"), { target: { value: "18-20" } });

    expect(screen.getByText("ranking recomputed for weeks 18-20")).toBeInTheDocument();

    await waitFor(() => {
      const rows = within(screen.getByRole("table")).getAllByRole("row").slice(1);
      expect(within(rows[0]).getByText("Detail Rich")).toBeInTheDocument();
    });

    // the raw playoff z-score column ("Playoff") is a column-picker extra,
    // not a default column -- turn it on so its swapped-window value is
    // visible to assert against (Playoff Sched, the default column at this
    // position now, shows a letter grade derived from week_games instead)
    fireEvent.click(screen.getByRole("button", { name: "Columns" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Playoff" }));

    const rows = within(screen.getByRole("table")).getAllByRole("row").slice(1);
    const detailRichRow = rows.find((r) => within(r).queryByText("Detail Rich")) as HTMLElement;
    const detailRichCells = within(detailRichRow).getAllByRole("cell");
    const playoffCell = detailRichCells[detailRichCells.length - 1]; // appended extra column
    expect(playoffCell).toHaveTextContent("0.40"); // the "18-20" z, not the shipped 1.10

    // back to the shipped default -- exact original order restored, note gone
    fireEvent.change(screen.getByLabelText("Playoff weeks"), { target: { value: "19-21" } });

    expect(screen.queryByText(/ranking recomputed for weeks/)).not.toBeInTheDocument();
    await waitFor(() => {
      const restored = within(screen.getByRole("table")).getAllByRole("row").slice(1);
      expect(within(restored[0]).getByText("Ace Guard")).toBeInTheDocument();
    });
  });

  it("switching the playoff window updates the open detail panel's schedule week rows", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify(dataset), { status: 200 })),
    );

    render(<App />);
    await waitFor(() => expect(screen.getByText("Ace Guard")).toBeInTheDocument());

    fireEvent.click(screen.getByText("Detail Rich"));
    expect(screen.getByRole("heading", { name: "Detail Rich" })).toBeInTheDocument();
    expect(screen.getByText("Week 19").nextElementSibling).toHaveTextContent("4 games");

    fireEvent.change(screen.getByLabelText("Playoff weeks"), { target: { value: "18-20" } });

    await waitFor(() => expect(screen.getByText("Week 18")).toBeInTheDocument());
    expect(screen.getByText("Week 18").nextElementSibling).toHaveTextContent("2 games");
    expect(screen.getByText("Week 19").nextElementSibling).toHaveTextContent("4 games");
    expect(screen.getByText("Week 20").nextElementSibling).toHaveTextContent("2 games");
    expect(screen.queryByText("Week 21")).not.toBeInTheDocument();
  });

  it("composes the selected window with a Settings weight change to re-rank the Rankings table", async () => {
    // dedicated 3-player dataset (mirrors Settings.test.tsx's Alice/Bob/Cara
    // pattern): Alice's only signal is per_game, Bob's is a window-dependent
    // playoff_schedule z that differs between "19-21" (0) and "18-20" (10)
    const zeroScores = {
      per_game: 0,
      availability_adjusted: 0,
      expected_games: 0,
      role_usage: 0,
      playoff_schedule: 0,
      consensus: 0,
      team_environment: 0,
      category_scarcity: 0,
    };
    const alice = {
      ...fixturePlayers[0],
      player_id: "alice",
      name: "Alice",
      model: {
        ...fixturePlayers[0].model,
        final_rank: 1,
        component_scores: { ...zeroScores, per_game: 1 },
      },
      schedule: { ...fixturePlayers[0].schedule, windows: {} },
    };
    const bob = {
      ...fixturePlayers[0],
      player_id: "bob",
      name: "Bob",
      model: {
        ...fixturePlayers[0].model,
        final_rank: 2,
        component_scores: { ...zeroScores },
      },
      schedule: {
        ...fixturePlayers[0].schedule,
        windows: {
          "19-21": { week_games: null, playoff_games: null, playoff_b2bs: null, playoff_schedule_score: null, expected_playoff_games: null, playoff_value_z: 0 },
          "18-20": { week_games: null, playoff_games: null, playoff_b2bs: null, playoff_schedule_score: null, expected_playoff_games: null, playoff_value_z: 10 },
        },
      },
    };
    const smallDataset = {
      ...dataset,
      players: [alice, bob],
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify(smallDataset), { status: 200 })),
    );

    render(<App />);
    await waitFor(() => expect(screen.getByText("Alice")).toBeInTheDocument());

    // default window + default weights (per_game .4 > playoff_schedule .05):
    // Alice's .4*1=.4 beats Bob's window-swapped 0 either way -- Alice #1
    let rows = within(screen.getByRole("table")).getAllByRole("row").slice(1);
    expect(within(rows[0]).getByText("Alice")).toBeInTheDocument();

    // move all weight onto playoff_schedule in Settings...
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    fireEvent.change(screen.getByLabelText("Per-game production"), { target: { value: "0" } });
    fireEvent.change(screen.getByLabelText("Playoff schedule"), { target: { value: "1" } });

    // ...then switch to "18-20", where Bob's swapped z (10) now dominates
    // Alice's per_game score (now weighted 0) -- both changes must compose
    fireEvent.change(screen.getByLabelText("Playoff weeks"), { target: { value: "18-20" } });
    fireEvent.click(screen.getByRole("button", { name: "Rankings" }));

    await waitFor(() => {
      rows = within(screen.getByRole("table")).getAllByRole("row").slice(1);
      expect(within(rows[0]).getByText("Bob")).toBeInTheDocument();
    });
  });

  describe("punt build", () => {
    const ZERO = { fg_pct: 0, ft_pct: 0, tpm: 0, pts: 0, reb: 0, ast: 0, stl: 0, blk: 0, tov: 0 };
    const zeroScores = {
      per_game: 0,
      availability_adjusted: 0,
      expected_games: 0,
      role_usage: 0,
      playoff_schedule: 0,
      consensus: 0,
      team_environment: 0,
      category_scarcity: 0,
    };

    // full 9cat sum: Balanced = 0.5*9 = 4.5 > Poor FT Big = -7.6+3+3+2+1 = 1.4
    // (Balanced leads, shipped final_rank 1/2 below). Punting ft_pct: Poor FT
    // Big's sum becomes 3+3+2+1 = 9 > Balanced's 4.5-0.5 = 4.0 -- the big jumps
    // above the balanced player, exactly as hand math predicts.
    const poorFtBig = {
      ...fixturePlayers[0],
      player_id: "poor-ft-big",
      name: "Poor FT Big",
      fantasy: {
        ...fixturePlayers[0].fantasy,
        per_game_zscores: { ...ZERO, ft_pct: -7.6, reb: 3, blk: 3, fg_pct: 2, pts: 1 },
      },
      model: { ...fixturePlayers[0].model, final_rank: 2, component_scores: { ...zeroScores } },
      schedule: { ...fixturePlayers[0].schedule, windows: {} },
    };
    const balanced = {
      ...fixturePlayers[0],
      player_id: "balanced",
      name: "Balanced",
      fantasy: {
        ...fixturePlayers[0].fantasy,
        per_game_zscores: { fg_pct: 0.5, ft_pct: 0.5, tpm: 0.5, pts: 0.5, reb: 0.5, ast: 0.5, stl: 0.5, blk: 0.5, tov: 0.5 },
      },
      model: { ...fixturePlayers[0].model, final_rank: 1, component_scores: { ...zeroScores } },
      schedule: { ...fixturePlayers[0].schedule, windows: {} },
    };
    const puntDataset = { ...dataset, players: [balanced, poorFtBig] };

    // the popover's checkbox list is only in the DOM tree meaningfully once
    // opened -- match RankingsTable's own Columns-picker interaction style
    function openPuntPicker() {
      fireEvent.click(screen.getByRole("button", { name: /^Punt:/ }));
    }

    it("checking punt FT% re-ranks the poor-FT big above the balanced player, as hand math predicts", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(new Response(JSON.stringify(puntDataset), { status: 200 })),
      );

      render(<App />);
      await waitFor(() => expect(screen.getByText("Balanced")).toBeInTheDocument());

      // shipped default: Balanced (full 9cat sum wins) leads, no punt note
      let rows = within(screen.getByRole("table")).getAllByRole("row").slice(1);
      expect(within(rows[0]).getByText("Balanced")).toBeInTheDocument();
      expect(screen.queryByText(/ranked for punt/)).not.toBeInTheDocument();

      openPuntPicker();
      fireEvent.click(screen.getByRole("checkbox", { name: "FT%" }));

      expect(screen.getByText("ranked for punt FT% build")).toBeInTheDocument();
      await waitFor(() => {
        rows = within(screen.getByRole("table")).getAllByRole("row").slice(1);
        expect(within(rows[0]).getByText("Poor FT Big")).toBeInTheDocument();
      });
    });

    it("checking multiple categories composes -- a 3-punt case re-ranks exactly as hand math predicts", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(new Response(JSON.stringify(puntDataset), { status: 200 })),
      );

      render(<App />);
      await waitFor(() => expect(screen.getByText("Balanced")).toBeInTheDocument());

      // punting ft_pct + ast + stl: Poor FT Big's sum is untouched (it never
      // had ast/stl set) at reb(3)+blk(3)+fg_pct(2)+pts(1) = 9; Balanced drops
      // to 0.5 * 6 remaining categories = 3.0 -- Poor FT Big (9) still wins
      openPuntPicker();
      fireEvent.click(screen.getByRole("checkbox", { name: "FT%" }));
      fireEvent.click(screen.getByRole("checkbox", { name: "AST" }));
      fireEvent.click(screen.getByRole("checkbox", { name: "ST" }));

      expect(screen.getByText("ranked for punt FT% + AST + ST build")).toBeInTheDocument();
      await waitFor(() => {
        const rows = within(screen.getByRole("table")).getAllByRole("row").slice(1);
        expect(within(rows[0]).getByText("Poor FT Big")).toBeInTheDocument();
      });
    });

    it("unchecking all punted categories restores the shipped order", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(new Response(JSON.stringify(puntDataset), { status: 200 })),
      );

      render(<App />);
      await waitFor(() => expect(screen.getByText("Balanced")).toBeInTheDocument());

      openPuntPicker();
      fireEvent.click(screen.getByRole("checkbox", { name: "FT%" }));
      fireEvent.click(screen.getByRole("checkbox", { name: "AST" }));
      await waitFor(() => {
        const rows = within(screen.getByRole("table")).getAllByRole("row").slice(1);
        expect(within(rows[0]).getByText("Poor FT Big")).toBeInTheDocument();
      });

      fireEvent.click(screen.getByRole("checkbox", { name: "FT%" }));
      fireEvent.click(screen.getByRole("checkbox", { name: "AST" }));

      expect(screen.queryByText(/ranked for punt/)).not.toBeInTheDocument();
      await waitFor(() => {
        const rows = within(screen.getByRole("table")).getAllByRole("row").slice(1);
        expect(within(rows[0]).getByText("Balanced")).toBeInTheDocument();
      });
    });

    it("the picker button's label reflects the current selections", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(new Response(JSON.stringify(puntDataset), { status: 200 })),
      );

      render(<App />);
      await waitFor(() => expect(screen.getByText("Balanced")).toBeInTheDocument());

      expect(screen.getByRole("button", { name: "Punt: none" })).toBeInTheDocument();

      openPuntPicker();
      fireEvent.click(screen.getByRole("checkbox", { name: "FT%" }));
      expect(screen.getByRole("button", { name: "Punt: FT%" })).toBeInTheDocument();

      fireEvent.click(screen.getByRole("checkbox", { name: "AST" }));
      expect(screen.getByRole("button", { name: "Punt: FT%, AST" })).toBeInTheDocument();
    });

    it("popover a11y: aria-expanded reflects open state, and Escape closes it", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(new Response(JSON.stringify(puntDataset), { status: 200 })),
      );

      render(<App />);
      await waitFor(() => expect(screen.getByText("Balanced")).toBeInTheDocument());

      const button = screen.getByRole("button", { name: "Punt: none" });
      expect(button).toHaveAttribute("aria-expanded", "false");

      openPuntPicker();
      expect(button).toHaveAttribute("aria-expanded", "true");
      expect(screen.getByRole("checkbox", { name: "FT%" })).toBeInTheDocument();

      fireEvent.keyDown(document, { key: "Escape" });
      expect(button).toHaveAttribute("aria-expanded", "false");
    });

    it("mutes the punted category's z column cell and the detail chart's punted bar", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(new Response(JSON.stringify(puntDataset), { status: 200 })),
      );

      render(<App />);
      await waitFor(() => expect(screen.getByText("Balanced")).toBeInTheDocument());

      openPuntPicker();
      fireEvent.click(screen.getByRole("checkbox", { name: "FT%" }));
      await waitFor(() => expect(screen.getByText(/ranked for punt/)).toBeInTheDocument());

      // turn on the FT% z column via the column picker
      fireEvent.click(screen.getByRole("button", { name: "Columns" }));
      fireEvent.click(screen.getByRole("checkbox", { name: "FT% z" }));

      const rows = within(screen.getByRole("table")).getAllByRole("row").slice(1);
      const balancedRow = rows.find((r) => within(r).queryByText("Balanced"));
      const ftCell = within(balancedRow as HTMLElement).getByText("0.50");
      expect(ftCell).toHaveClass("opacity-40");

      // open the detail panel and confirm the chart's punted bar is flagged
      fireEvent.click(screen.getByText("Balanced"));
      expect(screen.getByText(/FT%: 0\.50 \(punted\)/)).toBeInTheDocument();
    });
  });
});
