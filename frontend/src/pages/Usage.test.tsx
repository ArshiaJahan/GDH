import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  get: vi.fn(async (p: string): Promise<any> => ({})),
  post: vi.fn(async (p: string, b?: any): Promise<any> => ({})),
}));

vi.mock("../lib/api", () => ({ ...api, api: vi.fn() }));
vi.mock("../lib/native", () => ({ downloadFile: vi.fn() }));
vi.mock("../components/UsageCharts", () => ({ TokensChart: () => null, CostChart: () => null, ElevenChart: () => null }));
vi.mock("../lib/store", () => ({
  actions: { toast: vi.fn(), onEvent: vi.fn(() => () => {}), openSession: vi.fn() },
  useStore: (sel: any) => sel({ sessions: [{ id: "s1", title: "Boss fight", deleted: false }] }),
}));

import { UsagePage } from "./Usage";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const ROW = { ledger_usd: 0.5, subscription_estimated_usd: 0.25, tokens: 1000, attempts: 3, failures: 1 };
const attribution = (group: string) => ({
  group_by: group,
  rows: group === "task"
    ? [{ task_id: "t1", task_attribution: null, task_code: "Task00007", task_title: "Add jump", ...ROW },
       { task_id: null, task_attribution: "ambiguous", task_code: null, task_title: null, ...ROW },
       { task_id: null, task_attribution: null, task_code: null, task_title: null, ...ROW }]
    : [{ role: "main", ...ROW }],
  totals: ROW,
  next_offset: null,
});

function mockGet(traces: () => Promise<any>) {
  api.get.mockImplementation(async (p: string) => {
    if (p.startsWith("/usage/attribution")) return attribution(new URLSearchParams(p.split("?")[1]).get("group_by")!);
    if (p.startsWith("/traces")) return traces();
    if (p.startsWith("/usage/models") || p.startsWith("/usage/comparison")) return [];
    if (p === "/status") return { providers: [], models: {} };
    return null;
  });
}

const calls = (prefix: string) => api.get.mock.calls.map((c) => c[0] as string).filter((p) => p.startsWith(prefix));

describe("Cost attribution", () => {
  it("regroups through the grouping control and labels legacy and ambiguous spend", async () => {
    mockGet(async () => ({ traces: [] }));
    render(<UsagePage />);
    const section = await screen.findByRole("region", { name: "Cost attribution" });
    await within(section).findByText("Task00007 Add jump");
    expect(within(section).getByText("Ambiguous")).toBeTruthy();
    expect(within(section).getByText("Legacy")).toBeTruthy();
    expect(within(section).getByText("Ledger cost")).toBeTruthy();
    expect(within(section).getByText("Subscription estimate")).toBeTruthy();

    fireEvent.click(within(section).getByRole("button", { name: "Agent role" }));
    await within(section).findByText("main");
    expect(calls("/usage/attribution").some((p) => p.includes("group_by=role"))).toBe(true);
  });

  it("shows an empty state for a session with no traces", async () => {
    mockGet(async () => ({ traces: [], next_cursor: null }));
    const { container } = render(<UsagePage />);
    await screen.findByRole("region", { name: "Cost attribution" });
    const details = container.querySelector("details")!;
    details.open = true;
    fireEvent(details, new Event("toggle"));
    fireEvent.change(screen.getByLabelText("Trace session"), { target: { value: "s1" } });
    await screen.findByText("No traces recorded for this session.");
    expect(calls("/traces")[0]).toContain("session_id=s1");
  });

  it("keeps the usage panel when the traces call fails", async () => {
    mockGet(async () => { throw new Error("traces down"); });
    const { container } = render(<UsagePage />);
    await screen.findByText("Task00007 Add jump");
    const details = container.querySelector("details")!;
    details.open = true;
    fireEvent(details, new Event("toggle"));
    fireEvent.change(screen.getByLabelText("Trace session"), { target: { value: "s1" } });
    await waitFor(() => expect(screen.getByRole("alert").textContent).toBe("traces down"));
    expect(screen.getByText("Task00007 Add jump")).toBeTruthy();
  });
});
