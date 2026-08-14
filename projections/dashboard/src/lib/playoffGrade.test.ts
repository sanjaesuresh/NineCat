import { describe, expect, it } from "vitest";
import { formatGrade, gradePlayoffSchedule, playoffGradeSortValue } from "./playoffGrade";

describe("gradePlayoffSchedule", () => {
  it("grades a perfectly even 4/4/4 week as A+ (12)", () => {
    expect(gradePlayoffSchedule({ 19: 4, 20: 4, 21: 4 })).toEqual({ grade: "A+", total: 12 });
  });

  it("grades an A-average, high-spread 5/4/3 week as A- (12)", () => {
    expect(gradePlayoffSchedule({ 19: 5, 20: 4, 21: 3 })).toEqual({ grade: "A-", total: 12 });
  });

  it("grades an A-average, single-game-spread 4/4/3 week as A (11), no modifier", () => {
    expect(gradePlayoffSchedule({ 19: 4, 20: 4, 21: 3 })).toEqual({ grade: "A", total: 11 });
  });

  it("grades an exact-3.0-average, even 3/3/3 week as B+ (9)", () => {
    expect(gradePlayoffSchedule({ 19: 3, 20: 3, 21: 3 })).toEqual({ grade: "B+", total: 9 });
  });

  it("grades a 3.33-average, single-game-spread 4/3/3 week as B (10), no modifier", () => {
    expect(gradePlayoffSchedule({ 19: 4, 20: 3, 21: 3 })).toEqual({ grade: "B", total: 10 });
  });

  it("grades an even 2/2/2 week as D+ (6)", () => {
    expect(gradePlayoffSchedule({ 19: 2, 20: 2, 21: 2 })).toEqual({ grade: "D+", total: 6 });
  });

  it("grades an even 1/1/1 week as F (3) with no modifier", () => {
    expect(gradePlayoffSchedule({ 19: 1, 20: 1, 21: 1 })).toEqual({ grade: "F", total: 3 });
  });

  it("returns null for a null schedule", () => {
    expect(gradePlayoffSchedule(null)).toBeNull();
  });

  it("returns null for an empty schedule", () => {
    expect(gradePlayoffSchedule({})).toBeNull();
  });

  it("returns null when any week's game count is null (schedule not yet published for that week)", () => {
    expect(gradePlayoffSchedule({ 19: 4, 20: null, 21: 4 })).toBeNull();
  });
});

describe("formatGrade", () => {
  it('formats a grade as "A+ (12)"', () => {
    expect(formatGrade({ grade: "A+", total: 12 })).toBe("A+ (12)");
  });

  it("formats null as an em-dash", () => {
    expect(formatGrade(null)).toBe("—");
  });
});

describe("playoffGradeSortValue", () => {
  it("returns null for a null or ungradeable schedule", () => {
    expect(playoffGradeSortValue(null)).toBeNull();
    expect(playoffGradeSortValue({ 19: null })).toBeNull();
  });

  it("orders by total games first", () => {
    const lower = playoffGradeSortValue({ 19: 2, 20: 2, 21: 2 }); // total 6
    const higher = playoffGradeSortValue({ 19: 4, 20: 4, 21: 4 }); // total 12
    expect(lower).not.toBeNull();
    expect(higher).not.toBeNull();
    expect((higher as number) > (lower as number)).toBe(true);
  });

  it("breaks an equal-total tie in favor of the more consistent (lower-spread) schedule", () => {
    const even = playoffGradeSortValue({ 19: 4, 20: 4, 21: 4 }); // total 12, spread 0
    const uneven = playoffGradeSortValue({ 19: 5, 20: 4, 21: 3 }); // total 12, spread 2
    expect(even).toBe(12);
    expect(uneven).toBe(11.8);
    expect((even as number) > (uneven as number)).toBe(true);
  });
});
