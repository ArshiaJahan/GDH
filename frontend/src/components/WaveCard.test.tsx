// The run_wave renderer: units with scopes and status, merge queue, breaker strikes and the
// discoveries of each unit's HANDOFF, from GET /api/waves/{id}.
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const WAVE = {
  id: "wave_0123456789abcdef", session_id: "s", campaign_id: null, n: 2, status: "paused", strikes: 1, session_strikes: 1,
  created_at: 1, closed_at: null, name: "enemy prefabs", merge_queue: ["sub_a", "sub_b"],
  units: [
    { wave_id: "wave_0123456789abcdef", sub_id: "sub_a", name: "grunt", scope: ["Assets/Game/Enemies/Grunt"], read_only: false,
      status: "conflict", merged: false, discoveries: "built: grunt", conflicts: ["Assets/Game/Enemies/Grunt/Grunt.prefab"],
      branch: "gdw/sub_a", handoff: { built: "grunt prefab", discoveries: "Enemies share one HitFlash material" } },
    { wave_id: "wave_0123456789abcdef", sub_id: "sub_b", name: "bat", scope: ["Assets/Game/Enemies/Bat"], read_only: false,
      status: "done", merged: false, discoveries: null, branch: "gdw/sub_b", handoff: null },
    { wave_id: "wave_0123456789abcdef", sub_id: "sub_c", name: "survey", scope: ["Assets/Game (read-only)"], read_only: true,
      status: "dead", merged: false, discoveries: null, reason: "finished without a HANDOFF block", handoff: null },
  ],
};
const get = vi.hoisted(() => vi.fn(async () => WAVE));
vi.mock("../lib/api", async (orig) => ({ ...(await orig<typeof import("../lib/api")>()), get }));

import { toneOf, unitDetail, WaveCard, waveIdOf } from "./WaveCard";

afterEach(() => { cleanup(); get.mockClear(); });

describe("WaveCard", () => {
  it("finds the wave id in the tool result", () => {
    expect(waveIdOf('Started fleet wave 2 "x" (wave_0123456789abcdef): 2 writing unit(s)')).toBe("wave_0123456789abcdef");
    expect(waveIdOf("Wave refused")).toBeUndefined();
    expect(toneOf("dead")).toBe("var(--bad)");
    expect(unitDetail(WAVE.units[2] as any)).toBe("requeue · finished without a HANDOFF block");
  });

  it("shows units, scopes, the merge queue, breaker strikes and discoveries", async () => {
    const b = { type: "tool_use", id: "t1", name: "run_wave", input: { name: "enemy prefabs", units: [] } };
    const result = { type: "tool_result", content: [{ type: "text", text: "Started fleet wave 2 (wave_0123456789abcdef)" }] };
    render(<WaveCard b={b} result={result} />);
    expect(await screen.findByText("Wave 2 · enemy prefabs")).toBeTruthy();
    expect(get).toHaveBeenCalledWith("/waves/wave_0123456789abcdef");
    expect(screen.getByText("breaker 1/2")).toBeTruthy();
    expect(screen.getByText("Merge queue: grunt → bat")).toBeTruthy();
    expect(screen.getByText("Assets/Game/Enemies/Grunt")).toBeTruthy();
    expect(screen.getByText("conflicts in Assets/Game/Enemies/Grunt/Grunt.prefab")).toBeTruthy();
    fireEvent.click(screen.getByText("grunt"));
    expect(screen.getByText("Enemies share one HitFlash material")).toBeTruthy();
  });

  it("falls back to the plain tool row when the wave was refused", () => {
    const b = { type: "tool_use", id: "t2", name: "run_wave", input: { name: "w", units: [] } };
    render(<WaveCard b={b} result={{ type: "tool_result", is_error: true, content: [{ type: "text", text: "Wave refused:" }] }} />);
    expect(get).not.toHaveBeenCalled();
  });
});
