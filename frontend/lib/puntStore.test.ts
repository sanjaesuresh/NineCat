import { beforeEach, describe, expect, it, vi } from "vitest";
import { getPunts, resetPunts, subscribe, togglePunt } from "./puntStore";

// module-level state persists across tests in the same file — reset before every case
// so selections made in one test can't leak into the next
beforeEach(() => {
  resetPunts();
});

describe("puntStore", () => {
  it("defaults to free-throw percentage and turnovers", () => {
    expect(getPunts()).toEqual(["ftp", "to"]);
  });

  it("removes a category that is currently punted", () => {
    togglePunt("ftp");
    expect(getPunts()).toEqual(["to"]);
  });

  it("adds a category that is not punted, preserving insertion order", () => {
    togglePunt("ftp");
    togglePunt("reb");
    expect(getPunts()).toEqual(["to", "reb"]);
  });

  it("evicts the oldest selection when a third category is picked", () => {
    // default order is [ftp, to]; picking pts should drop ftp (the oldest) and keep [to, pts]
    togglePunt("pts");
    expect(getPunts()).toEqual(["to", "pts"]);
  });

  it("supports re-adding a category after it was evicted", () => {
    togglePunt("pts"); // -> [to, pts], evicts ftp
    togglePunt("reb"); // -> [pts, reb], evicts to
    expect(getPunts()).toEqual(["pts", "reb"]);
  });

  it("notifies subscribers exactly once per toggle", () => {
    const listener = vi.fn();
    const unsubscribe = subscribe(listener);

    togglePunt("pts");
    expect(listener).toHaveBeenCalledTimes(1);

    togglePunt("ftp");
    expect(listener).toHaveBeenCalledTimes(2);

    unsubscribe();
    togglePunt("reb");
    expect(listener).toHaveBeenCalledTimes(2);
  });

  it("supports multiple independent subscribers", () => {
    const a = vi.fn();
    const b = vi.fn();
    const unsubA = subscribe(a);
    const unsubB = subscribe(b);

    togglePunt("pts");

    expect(a).toHaveBeenCalledTimes(1);
    expect(b).toHaveBeenCalledTimes(1);

    // unsubscribe so these listeners don't leak into later tests' notification loops
    unsubA();
    unsubB();
  });

  it("isolates a throwing listener so later-registered listeners still fire and the error does not escape togglePunt", () => {
    const thrower = vi.fn(() => {
      throw new Error("boom");
    });
    const normal = vi.fn();
    // subscribe the thrower first so it runs before `normal` in Set insertion order
    const unsubThrower = subscribe(thrower);
    const unsubNormal = subscribe(normal);
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    expect(() => togglePunt("pts")).not.toThrow();
    expect(thrower).toHaveBeenCalledTimes(1);
    expect(normal).toHaveBeenCalledTimes(1);

    errorSpy.mockRestore();
    unsubThrower();
    unsubNormal();
  });

  it("moves a category re-added after eviction to the newest slot, so the next pick evicts the other one", () => {
    // default [ftp, to] -> toggle ftp off -> [to] -> toggle ftp back on -> [to, ftp]
    // (ftp is now newest) -> toggle pts on -> must evict to (oldest), keeping [ftp, pts]
    togglePunt("ftp");
    togglePunt("ftp");
    togglePunt("pts");
    expect(getPunts()).toEqual(["ftp", "pts"]);
  });

  // useSyncExternalStore requires getSnapshot to return a referentially stable value when
  // nothing has changed, or React throws "getSnapshot should be cached" and loops forever
  it("returns the same array reference across repeated reads when nothing changed", () => {
    const first = getPunts();
    const second = getPunts();
    expect(first).toBe(second);
  });

  it("returns a new array reference only after a change", () => {
    const before = getPunts();
    togglePunt("pts");
    const after = getPunts();
    expect(after).not.toBe(before);
    // and the new reference is itself stable until the next change
    expect(getPunts()).toBe(after);
  });
});
