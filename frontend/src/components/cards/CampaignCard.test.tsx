// The Campaign card: hidden outside campaign sessions; status, phase, done_when chips with their
// last results, next action, and the buttons post to the campaign routes.
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const DETAIL = {
  id: "cmp_1", title: "Boss Rush", kind: "campaign", template: "milestone", template_title: "Milestone", status: "running", phase: 1,
  autopilot: true, budget_usd: 10, spend_usd: 1.2, reason: null, next_action: "Phase 2 Build: make these pass: gate L1",
  phases: [
    { name: "Spec", type: "plan", skills: [], done_when: [{ type: "file_exists", path: "docs/*.md" }], status: "done" },
    { name: "Build", type: "build", skills: ["compile-fix-loop"], status: "running", retries: 2, retries_max: 3,
      done_when: [{ type: "gate", level: "L1" }, { type: "git_clean" }],
      results: [{ index: 0, type: "gate", label: "gate L1", status: "fail", detail: "2 compile errors" }] },
  ],
};

const detail = vi.hoisted(() => vi.fn());
const act_ = vi.hoisted(() => vi.fn(async () => ({})));
const check = vi.hoisted(() => vi.fn(async () => ({ results: [{ status: "fail" }] })));
vi.mock("../../lib/campaigns", async (orig) => ({ ...(await orig<any>()), campaignsApi: { detail, act: act_, check } }));
const go = vi.hoisted(() => vi.fn());
vi.mock("../../lib/store", () => ({ actions: { toast: vi.fn(), onEvent: () => () => {}, go } }));
vi.mock("../SidePanel", () => ({ Card: ({ title, children }: { title: string; children: ReactNode }) => <div><h2>{title}</h2>{children}</div> }));

import { CampaignCard } from "./CampaignCard";

afterEach(() => { cleanup(); detail.mockReset(); act_.mockClear(); check.mockClear(); });
const session = (settings: Record<string, unknown>) => ({ id: "s1", folder: "/p", status: "idle", settings }) as any;

describe("CampaignCard", () => {
  it("renders nothing outside a campaign session", async () => {
    const { container } = render(<CampaignCard s={session({})} />);
    await act(async () => {});
    expect(container.innerHTML).toBe("");
    expect(detail).not.toHaveBeenCalled();
  });

  it("shows the phase, its checks and the next action, and runs the buttons", async () => {
    detail.mockResolvedValue(DETAIL);
    render(<CampaignCard s={session({ campaign_id: "cmp_1" })} />);
    await act(async () => {});
    expect(detail).toHaveBeenCalledWith("cmp_1");
    expect(screen.getByText("Campaign")).toBeTruthy();
    expect(screen.getByTestId("campaign-status").textContent).toBe("Running");
    expect(screen.getByText(/Phase 2\/2 Build \(build\)/)).toBeTruthy();
    expect(screen.getByText("gate L1")).toBeTruthy();
    expect(screen.getByText("2 compile errors")).toBeTruthy();
    expect(screen.getByText("git clean")).toBeTruthy();
    expect(screen.getByText("Retries left: 2/3")).toBeTruthy();
    expect(screen.getByTestId("campaign-next").textContent).toContain("make these pass");
    await act(async () => { fireEvent.click(screen.getByText(/Run phase checks/)); });
    expect(check).toHaveBeenCalledWith("cmp_1");
    await act(async () => { fireEvent.click(screen.getByText(/Pause/)); });
    expect(act_).toHaveBeenCalledWith("cmp_1", "pause");
    fireEvent.click(screen.getByText(/Details/));
    expect(go).toHaveBeenCalledWith("campaigns", { id: "cmp_1" });
  });

  it("offers Resume and Approve plan when the campaign waits", async () => {
    detail.mockResolvedValue({ ...DETAIL, status: "parked", reason: "budget reached" });
    render(<CampaignCard s={session({ campaign_id: "cmp_1" })} />);
    await act(async () => {});
    expect(screen.getByText("budget reached")).toBeTruthy();
    expect(screen.queryByText(/Pause/)).toBeNull();
    await act(async () => { fireEvent.click(screen.getByText(/Resume/)); });
    expect(act_).toHaveBeenCalledWith("cmp_1", "resume");
  });
});
