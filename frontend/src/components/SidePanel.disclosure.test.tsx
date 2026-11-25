import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { Session } from "../lib/store";

const { get, state } = vi.hoisted(() => ({ get: vi.fn(), state: { session: null as Session | null } }));
vi.mock("../lib/api", () => ({ get, patch: vi.fn(), post: vi.fn() }));
vi.mock("../lib/native", () => ({ pickFolder: vi.fn() }));
vi.mock("../lib/store", () => ({
  actions: { toast: vi.fn() },
  sessionProfile: () => "default",
  useStore: (select: (s: any) => unknown) => select({ currentId: "s1", sessions: [state.session], messages: {}, jobs: [], appState: {} }),
}));
vi.mock("./cards/CampaignCard", () => ({ CampaignCard: () => null }));
vi.mock("./cards/ChangesCard", () => ({ ChangesCard: () => null }));
vi.mock("./cards/ConnectorsCard", () => ({ ConnectorsCard: () => null, SharedToolsCard: () => null }));
vi.mock("./cards/OutputsCard", () => ({ OutputsCard: () => null }));
vi.mock("./cards/QualityCard", () => ({ QualityCard: () => null }));
vi.mock("./ui", () => ({
  EffortMeter: () => null, fmtDuration: String, fmtTokens: String, fmtUsd: String,
  isTier: () => false, modelLabel: String, modelName: String, providerLabel: String,
  providerOf: () => "anthropic", tiersOf: () => [], useModelCatalog: () => {},
}));

import { SidePanel } from "./SidePanel";

const context = (progressive: boolean) => ({
  total: 1000, window: 10_000, fraction: 0.1, calibrated: false, level: "ok",
  parts: { system: 100, tools: 100, skills: 600, messages: 100, attachments: 100 },
  ...(progressive ? { skill_parts: { pinned: 100, index: 200, loaded: 300 } } : {}),
});

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  state.session = {
    id: "s1", title: "Skills", status: "idle", created_at: 0, updated_at: 0, pinned: false, folder: null,
    model: "claude-opus-5-5", effort: "medium", account: "default", mode: "ask", harness: "builtin", location: "local",
    group_id: null, sort_order: 0, archived: false, archived_at: null, deleted: false, deleted_at: null,
    activity_at: null, last_read_at: null, unread: false, last_error: null, forked_from: null,
    settings: { skill_mode: "progressive", pinned_skills: ["delegation"], loaded_skills: [] },
  };
  get.mockImplementation(async (path: string) => {
    if (path === "/sessions/s1/context") return context(state.session?.settings.skill_mode === "progressive");
    if (path === "/usage/session/s1") return { models: [] };
    if (path === "/environment") return { harnesses: { builtin: true }, models: [] };
    return [];
  });
});
afterEach(cleanup);

it("shows pinned, index and loaded-in-history token rows for progressive sessions", async () => {
  render(<SidePanel />);
  await act(async () => {});
  for (const [label, tokens] of [["Pinned", "100"], ["Index", "200"], ["Loaded (in history)", "300"]]) {
    const row = screen.getByText(label).closest("tr");
    expect(row?.textContent).toContain(tokens);
  }
  expect(screen.queryByText("Skills")).toBeNull();
});

it("retains the single Skills row for legacy sessions", async () => {
  state.session!.settings = {};
  render(<SidePanel />);
  await act(async () => {});
  expect(screen.getByText("Skills").closest("tr")?.textContent).toContain("600");
  expect(screen.queryByText("Loaded (in history)")).toBeNull();
  expect(screen.queryByText("Pinned")).toBeNull();
});

it("refreshes the live split after pin or load settings change", async () => {
  const { rerender } = render(<SidePanel />);
  await act(async () => {});
  const contextCalls = () => get.mock.calls.filter(([path]) => path === "/sessions/s1/context").length;
  const initial = contextCalls();
  state.session = { ...state.session!, settings: { ...state.session!.settings, pinned_skills: ["delegation", "grilling"] } };
  rerender(<SidePanel />);
  await act(async () => {});
  expect(contextCalls()).toBe(initial + 1);
  state.session = { ...state.session!, settings: { ...state.session!.settings, loaded_skills: ["graphify"] } };
  rerender(<SidePanel />);
  await act(async () => {});
  expect(contextCalls()).toBe(initial + 2);
});

it("no longer shows the gallery (it is a session tab now)", async () => {
  render(<SidePanel />);
  await act(async () => {});
  expect(screen.queryByText(/^Gallery/)).toBeNull();
  expect(screen.queryByLabelText("Screenshot prompt")).toBeNull();
  expect(get.mock.calls.some(([path]) => String(path).includes("/gallery"))).toBe(false);
});

it("shows skill tokens saved and the API-price total, not as a receipt", async () => {
  get.mockImplementation(async (path: string) => {
    if (path === "/sessions/s1/context") return {
      ...context(true),
      skill_savings: { full_tokens: 50_000, now_tokens: 5_000, saved_tokens_per_call: 45_000, main_calls: 4,
        saved_tokens_session: 180_000, saved_usd_per_call: 0.225, saved_usd_per_call_cached: 0.0225,
        saved_usd_session: 0.9, saved_usd_session_cached: 0.09, priced: true },
    };
    if (path === "/usage/session/s1") return {
      models: [{ model: "claude-opus-5-5", billing: "subscription", input: 10, output: 5, cached: 0, cost: 0.4, api_price: 0.4 }],
      total_cost: 0, subscription_estimated: 0.4, api_price_total: 0.4,
    };
    if (path === "/environment") return { harnesses: { builtin: true }, models: [] };
    return [];
  });
  render(<SidePanel />);
  await act(async () => {});
  expect(screen.getByText("Skill tokens saved per call").closest("div")?.textContent).toContain("45000");
  expect(screen.getByText("Saved this session (4 calls)").closest("div")?.textContent).toContain("180000");
  expect(screen.getByText(/per call · .* this session at API prices/).textContent).toContain("0.0225–0.225");
  expect(screen.getByText("At API prices").closest("div")?.textContent).toContain("0.4");
});

it("hides the savings line when progressive loading saves nothing", async () => {
  get.mockImplementation(async (path: string) => {
    if (path === "/sessions/s1/context") return { ...context(true), skill_savings: { saved_tokens_per_call: 0, main_calls: 0, priced: true } };
    if (path === "/usage/session/s1") return { models: [] };
    if (path === "/environment") return { harnesses: { builtin: true }, models: [] };
    return [];
  });
  render(<SidePanel />);
  await act(async () => {});
  expect(screen.queryByText("Skill tokens saved per call")).toBeNull();
});
