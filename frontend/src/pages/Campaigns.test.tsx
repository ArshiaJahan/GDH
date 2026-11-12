// The Campaigns page: list with status, phase and spend; detail with phases and checkpoints.
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const ROW = {
  id: "cmp_1", slug: "boss-rush", title: "Boss Rush", kind: "campaign", template: "milestone", template_title: "Milestone", folder: "/p/game",
  file: ".gamedevworkstation/campaigns/boss-rush.md", status: "awaiting_approval", phase: -1, autopilot: false, budget_usd: 10, spend_usd: 0.5, sessions: 1,
  max_sessions: 12, updated_at: 1, last_activity: 1, reason: "waiting for your approval of the plan",
  phases: [{ name: "Build", type: "build", skills: [], done_when: [{ type: "gate", level: "L1" }], status: "pending", retries: 3, retries_max: 3,
    checkpoint: null }],
};
const METRICS = { campaigns: 1, spend_usd: 0.5, stories: 0, cost_per_story_usd: null, wall_s_per_story: null, first_pass_gate_rate: 0.5,
  gate_retries_per_phase: null, escalations: 1, parks_by_reason: {} };
const DETAIL = { ...ROW, next_action: "Waiting for you to approve the plan.", current_session: "s1", path: "/p/game/.gamedevworkstation/campaigns/boss-rush.md",
  session_chain: [{ campaign_id: "cmp_1", session_id: "s1", phase: -1, started_at: 1, ended_at: null, end_reason: null, title: "Boss Rush · plan", exists: true }],
  checkpoints: [{ phase: 1, name: "Build", ref: "refs/gamedevworkstation/checkpoints/boss-rush/p1", sha: "abc", kind: "head", restore: "git restore --source=abc --staged --worktree -- .", ts: 1 }],
  doc: { design_target: [{ done: false, text: "Boss Rush starts from Title" }], scope: { stories: ["M3-S04"], paths: [], out_of_scope: [] }, constraints: "",
    coverage: "", review: "- [ ] question: which bosses?", decisions: "", discoveries: "", active: "", continuation: "", completion: "" }, state: {} };

const list = vi.hoisted(() => vi.fn());
const detail = vi.hoisted(() => vi.fn());
const act_ = vi.hoisted(() => vi.fn(async () => ({})));
vi.mock("../lib/campaigns", async (orig) => ({ ...(await orig<any>()), campaignsApi: { list, detail, act: act_, update: vi.fn(), chains: vi.fn(async () => ({ templates: [], errors: [] })) } }));
vi.mock("../lib/store", () => ({ actions: { toast: vi.fn(), onEvent: () => () => {}, go: vi.fn(), openSession: vi.fn(), setSkillChip: vi.fn() },
  useStore: (sel: (s: any) => unknown) => sel({ pageArgs: {}, appState: { tiers: {} } }) }));
vi.mock("../lib/native", () => ({ openLocalFile: vi.fn(), pickFolder: vi.fn() }));
vi.mock("../components/SafeMarkdown", () => ({ SafeMarkdown: ({ text }: { text: string }) => <div>{text}</div> }));

import { CampaignsPage } from "./Campaigns";

afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("CampaignsPage", () => {
  it("lists campaigns and opens the detail with its actions", async () => {
    list.mockResolvedValue({ campaigns: [ROW], metrics: METRICS });
    detail.mockResolvedValue(DETAIL);
    render(<CampaignsPage />);
    await act(async () => {});
    expect(screen.getByText("Boss Rush")).toBeTruthy();
    expect(screen.getByTestId("status-pill").textContent).toContain("Needs your approval");
    expect(screen.getByText("Phase plan")).toBeTruthy();
    expect(screen.getByText("$0.50 / $10")).toBeTruthy();
    expect(screen.getByText(/First-pass gate rate 50%/)).toBeTruthy();
    await act(async () => { fireEvent.click(screen.getByText("Boss Rush")); });
    expect(detail).toHaveBeenCalledWith("cmp_1");
    expect(screen.getByText("Boss Rush starts from Title")).toBeTruthy();
    expect(screen.getByText("git restore --source=abc --staged --worktree -- .")).toBeTruthy();
    expect(screen.getByText("• question: which bosses?")).toBeTruthy();
    await act(async () => { fireEvent.click(screen.getByText(/Approve plan/)); });
    expect(act_).toHaveBeenCalledWith("cmp_1", "approve_plan", {});
  });

  it("shows an empty state", async () => {
    list.mockResolvedValue({ campaigns: [], metrics: { ...METRICS, campaigns: 0 } });
    render(<CampaignsPage />);
    await act(async () => {});
    expect(screen.getByText("No campaigns or workflows yet.")).toBeTruthy();
  });
});
