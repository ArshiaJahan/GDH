// The Quality card: hidden for folders without a backlog or Unity project, ladder pills per story,
// evidence on click, and the buttons post to the ladder / hooks routes.
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const lvl = (level: string, state: string, extra: Record<string, unknown> = {}) =>
  ({ level, state, missing: [], evidence: [], shots: [], ...extra });
const REPORT = {
  enabled: true, project: "/p/game", unity: true, backlog: true, current: "M1",
  gates: [{ gate: "ladder.story_done", status: "fail", summary: "M1-S01", attempt: 1, level: null, started_at: Date.now() / 1000 }],
  stories: [{
    id: "M1-S01", title: "Movement", status: "doing", milestone: "M1", ok: false, override: null, missing: ["M1-S01-AC1: no observed test run"],
    levels: {
      L1: lvl("L1", "pass", { evidence: [{ id: "ev_1", level: "L1", status: "pass", source: "cmd:parse_unity_log.py", observed: "command", ts: Date.now() / 1000, path: null, item_id: null, subjects: [], summary: "0 compile error(s)", fresh: true }] }),
      L2: lvl("L2", "pending", { missing: ["M1-S01-AC1: no observed test run"] }),
      L3: lvl("L3", "n/a"), L4: lvl("L4", "n/a"), manual: lvl("manual", "n/a"),
    },
  }],
};

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn(async () => ({})));
vi.mock("../../lib/api", () => ({ get, post }));
vi.mock("../../lib/store", () => ({ actions: { toast: vi.fn(), onEvent: () => () => {} } }));
vi.mock("../SidePanel", () => ({ Card: ({ title, children }: { title: string; children: ReactNode }) => <div><h2>{title}</h2>{children}</div> }));
vi.mock("../items", () => ({ ItemViewer: () => null }));
vi.mock("../ui", () => ({ fmtAgo: () => "just now" }));

import { QualityCard } from "./QualityCard";

afterEach(() => { cleanup(); get.mockReset(); post.mockClear(); });

const session = (folder: string | null) => ({ id: "s1", folder, status: "idle", settings: {} }) as any;

describe("QualityCard", () => {
  it("renders nothing when the folder has no backlog or Unity project", async () => {
    get.mockImplementation(async (p: string) => (p.startsWith("/ladder") ? { ...REPORT, enabled: false, stories: [], gates: [] } : {}));
    const { container } = render(<QualityCard s={session("/p/plain")} />);
    await act(async () => {});
    expect(container.innerHTML).toBe("");
  });

  it("shows pills, evidence on click, and runs the gate buttons", async () => {
    get.mockImplementation(async (p: string) => {
      if (p.startsWith("/ladder")) return REPORT;
      if (p.startsWith("/hooks")) return { sources: [{ kind: "preset", name: "unity-router", state: "enabled", active: true }] };
      throw new Error("unexpected " + p);
    });
    render(<QualityCard s={session("/p/game")} />);
    await act(async () => {});
    expect(get).toHaveBeenCalledWith("/ladder?session_id=s1");
    expect(screen.getByText("Quality")).toBeTruthy();
    expect(screen.getByLabelText("L1 pass")).toBeTruthy();
    expect(screen.getByLabelText("L2 pending")).toBeTruthy();
    expect(screen.getByText("ladder.story_done")).toBeTruthy();
    expect((screen.getByLabelText("Unity gates") as HTMLInputElement).checked).toBe(true);

    fireEvent.click(screen.getByLabelText("L1 pass"));
    expect(screen.getByText("0 compile error(s)")).toBeTruthy();
    fireEvent.click(screen.getByLabelText("L2 pending"));
    expect(screen.getByTestId("ladder-detail").textContent).toContain("M1-S01-AC1: no observed test run");

    await act(async () => { fireEvent.click(screen.getByText(/Run compile gate/)); });
    expect(post).toHaveBeenCalledWith("/hooks/run", { session_id: "s1", gate: "unity.compile" });
    await act(async () => { fireEvent.click(screen.getByText(/Run critique/)); });
    expect(post).toHaveBeenCalledWith("/ladder/critique", { session_id: "s1", stories: ["M1-S01"] });
  });

  it("works without the hooks engine (toggle unavailable)", async () => {
    get.mockImplementation(async (p: string) => {
      if (p.startsWith("/ladder")) return REPORT;
      throw new Error("404");
    });
    render(<QualityCard s={session("/p/game")} />);
    await act(async () => {});
    expect((screen.getByLabelText("Unity gates") as HTMLInputElement).disabled).toBe(true);
    expect(screen.getByText("unavailable")).toBeTruthy();
  });
});
