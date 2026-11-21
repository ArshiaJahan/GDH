import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { get, post, list } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), list: vi.fn() }));
vi.mock("../lib/api", () => ({
  get, post, patch: vi.fn(), connect: vi.fn(), openEvents: vi.fn(), inTauri: () => false,
  galleryApi: { list, screenshot: vi.fn() },
  galleryMediaUrl: (e: { url: string | null }) => (e.url ? `http://x${e.url}` : null),
}));
vi.mock("../lib/native", () => ({ revealInFinder: vi.fn(async () => true) }));
vi.mock("./Chat", () => ({ Chat: () => <textarea aria-label="draft" /> }));
vi.mock("./ui", async (orig) => ({ ...(await orig<typeof import("./ui")>()), useModelCatalog: () => {} }));

import { actions, useStore } from "../lib/store";
import { SessionView } from "./SessionTabs";

const sub = (o: any) => ({
  id: "sub_0000000000000001", session_id: "s1", name: "scout", tier: "claude.fast", model: "claude-haiku-4-5", effort: "low", status: "running",
  worktree: null, started: 100, ended: null, cost_usd: 0.0123, tokens: { input: 1500, output: 300, reasoning: 0 }, result_preview: "", error: null, ...o,
});
const entry = (o: any) => ({ kind: "image", path: "/p/a.png", url: "/api/gallery/file/i?session_id=s1", title: "a.png", created_at: 1, source: "tool", status: "done", ...o });

beforeEach(() => {
  list.mockResolvedValue([]);
  get.mockResolvedValue({});
  post.mockResolvedValue({ stopped: true });
  useStore.setState({ currentId: "s1", page: "chat", sessions: [{ id: "s1", title: "S", unread: false } as any], subagents: {}, sessionTabs: {} });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

const tab = (n: string | RegExp) => screen.getByRole("tab", { name: n });

describe("session tabs", () => {
  it("defaults to Chat, switches tabs, keeps Chat mounted and remembers the tab per session", async () => {
    render(<SessionView />);
    expect(tab("Chat").getAttribute("aria-selected")).toBe("true");
    const draft = screen.getByLabelText("draft") as HTMLTextAreaElement;
    fireEvent.change(draft, { target: { value: "hello" } });
    fireEvent.click(tab(/Subagents/));
    expect(await screen.findByText("No subagents in this session yet.")).toBeTruthy();
    expect(screen.getByLabelText("draft")).toBe(draft); // same node, still mounted
    expect((screen.getByLabelText("draft") as HTMLTextAreaElement).value).toBe("hello");
    expect(draft.closest("[role=tabpanel]")!.hasAttribute("hidden")).toBe(true);
    expect(useStore.getState().sessionTabs.s1).toBe("subagents");
    expect(screen.getByRole("tabpanel", { name: /Subagents/ })).toBeTruthy();
    fireEvent.click(tab("Chat"));
    expect(draft.closest("[role=tabpanel]")!.hasAttribute("hidden")).toBe(false);
  });

  it("moves between tabs with the arrow keys, Home and End", () => {
    render(<SessionView />);
    fireEvent.keyDown(tab("Chat"), { key: "ArrowRight" });
    expect(tab(/Subagents/).getAttribute("aria-selected")).toBe("true");
    expect(document.activeElement).toBe(tab(/Subagents/));
    expect(tab(/Subagents/).getAttribute("tabindex")).toBe("0");
    expect(tab("Chat").getAttribute("tabindex")).toBe("-1");
    fireEvent.keyDown(tab(/Subagents/), { key: "ArrowRight" });
    expect(tab(/Gallery/).getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(tab(/Gallery/), { key: "ArrowRight" });
    expect(tab("Chat").getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(tab("Chat"), { key: "ArrowLeft" });
    expect(tab(/Gallery/).getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(tab(/Gallery/), { key: "Home" });
    expect(tab("Chat").getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(tab("Chat"), { key: "End" });
    expect(tab(/Gallery/).getAttribute("aria-selected")).toBe("true");
  });

  it("badges the running subagent count (this session only) and the gallery count", async () => {
    useStore.setState({ subagents: {
      a: sub({ id: "a" }), b: sub({ id: "b", status: "queued" }), c: sub({ id: "c", status: "done", ended: 110 }), d: sub({ id: "d", session_id: "other" }),
    } });
    list.mockResolvedValue([entry({ id: "1" }), entry({ id: "2" })]);
    render(<SessionView />);
    expect(tab(/Subagents/).textContent).toContain("2");
    expect(within(tab(/Subagents/)).getByLabelText("2 running")).toBeTruthy();
    expect(await within(tab(/Gallery/)).findByLabelText("2 items")).toBeTruthy();
    act(() => useStore.setState((s) => ({ subagents: { ...s.subagents, a: sub({ id: "a", status: "done", ended: 120 }) } })));
    expect(within(tab(/Subagents/)).getByLabelText("1 running")).toBeTruthy();
  });

  it("lists subagents newest first with statuses, tokens and cost, and updates live", () => {
    useStore.setState({ currentId: "s1", subagents: {
      a: sub({ id: "a", name: "old", status: "failed", started: 10, ended: 20 }),
      b: sub({ id: "b", name: "mid", status: "cancelled", started: 50, ended: 60 }),
      c: sub({ id: "c", name: "newest", status: "running", started: 90 }),
      d: sub({ id: "d", name: "queuedone", status: "queued", started: 80 }),
      e: sub({ id: "e", name: "finished", status: "done", started: 20, ended: 80 }),
    }, sessionTabs: { s1: "subagents" } });
    render(<SessionView />);
    const rows = screen.getAllByRole("listitem").map((r) => r.getAttribute("aria-label"));
    expect(rows).toEqual(["Subagent newest", "Subagent queuedone", "Subagent mid", "Subagent finished", "Subagent old"]);
    const newest = screen.getByLabelText("Subagent newest");
    expect(newest.textContent).toContain("running");
    expect(newest.textContent).toContain("claude.fast");
    expect(newest.textContent).toMatch(/\$0\.0\d+/);
    expect(screen.getByLabelText("Subagent old").textContent).toContain("failed");
    expect(screen.getByLabelText("Subagent mid").textContent).toContain("cancelled");
    expect(screen.getByLabelText("Subagent finished").textContent).toContain("done");
    expect(screen.queryByLabelText("Stop old")).toBeNull();
    act(() => useStore.setState((s) => ({ subagents: { ...s.subagents, f: sub({ id: "f", name: "fresh", started: 200 }) } })));
    expect(screen.getAllByRole("listitem")[0].getAttribute("aria-label")).toBe("Subagent fresh");
  });

  it("Stop posts to the stop endpoint, only for running or queued subagents", () => {
    useStore.setState({ subagents: { a: sub({ id: "a" }), b: sub({ id: "b", name: "done", status: "done", ended: 5 }) }, sessionTabs: { s1: "subagents" } });
    render(<SessionView />);
    expect(screen.queryByLabelText("Stop done")).toBeNull();
    fireEvent.click(screen.getByLabelText("Stop scout"));
    expect(post).toHaveBeenCalledWith("/subagents/a/stop");
  });

  it("expands a row to fetch the brief, result and worktree", async () => {
    useStore.setState({ subagents: { a: sub({ id: "a", status: "done", ended: 5 }) }, sessionTabs: { s1: "subagents" } });
    get.mockImplementation(async (p: string) => p === "/subagents/a" ? { ...sub({ id: "a" }), instructions: "Find the boss room", result: "It is in Cave.unity", worktree: "/wt/a" } : {});
    render(<SessionView />);
    expect(get).not.toHaveBeenCalledWith("/subagents/a");
    fireEvent.click(screen.getByRole("button", { name: /scout/ }));
    expect(await screen.findByText("Find the boss room")).toBeTruthy();
    expect(screen.getByText("It is in Cave.unity")).toBeTruthy();
    expect(screen.getByText("/wt/a")).toBeTruthy();
    expect(get).toHaveBeenCalledWith("/subagents/a");
  });

  it("shows the gallery grid with no row limit, and its empty state", async () => {
    list.mockResolvedValue(Array.from({ length: 12 }, (_, i) => entry({ id: `i${i}`, title: `pic${i}.png` })));
    useStore.setState({ sessionTabs: { s1: "gallery" } });
    render(<SessionView />);
    expect(await screen.findByAltText("pic11.png")).toBeTruthy();
    expect(within(screen.getByTestId("gallery-grid")).getAllByRole("listitem")).toHaveLength(12);
    fireEvent.click(screen.getByLabelText("Open pic3.png"));
    expect(screen.getByRole("dialog")).toBeTruthy();
    cleanup();
    list.mockResolvedValue([]);
    render(<SessionView />);
    expect(await screen.findByText("No media yet.")).toBeTruthy();
  });

  it("shows no tabs on the new-session screen", () => {
    useStore.setState({ currentId: null });
    render(<SessionView />);
    expect(screen.queryByRole("tablist")).toBeNull();
  });

  it("setSessionTab is available as a store action", () => {
    actions.setSessionTab("s1", "gallery");
    expect(useStore.getState().sessionTabs.s1).toBe("gallery");
  });
});
