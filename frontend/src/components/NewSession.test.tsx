// The new-session screen: greeting, Chat only vs Folder, recent folders, the Claude Code login
// notice, and Send creating a claude_code session with the chosen settings.
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type Status = { installed: boolean; logged_in: boolean } | null;
const api = vi.hoisted(() => ({ name: "Arshia J." as string | null, status: { installed: true, logged_in: true } as Status }));
const get = vi.hoisted(() => vi.fn(async (path: string): Promise<any> => {
  if (path === "/greeting") return { name: api.name };
  if (path.startsWith("/claude-code/status")) return api.status;
  if (path === "/skills") return { skills: [{ name: "graphify", description: "graphs" }] };
  if (path.includes("/messages/page")) return { messages: [], has_more: false, compacted: 0 };
  return [];
}));
const post = vi.hoisted(() => vi.fn(async (path: string, _body?: unknown): Promise<any> => (path === "/sessions" ? { id: "s9", title: "New session" } : {})));
vi.mock("../lib/api", () => ({ get, post, patch: vi.fn(), upload: vi.fn(), del: vi.fn(), fileUrl: (p: string) => p, inTauri: () => false }));
const pickFolder = vi.hoisted(() => vi.fn(async (): Promise<string | null> => "/Users/me/Games/Forklift"));
vi.mock("../lib/native", () => ({ pickFolder, revealInFinder: vi.fn(), downloadFile: vi.fn(), openLocalFile: vi.fn() }));

import { actions, useStore, type Session } from "../lib/store";
import { sessionActions } from "../lib/sessions";
import { Composer } from "./Composer";
import { NewSession, recentFolders } from "./NewSession";

const APP_STATE = {
  orchestrator: { model: "claude-opus-5-5", effort: "medium" }, modes: { default: "ask" },
  tiers: { "claude.fast": "claude-haiku-5-5", "claude.standard": "claude-sonnet-5-5", "claude.deep": "claude-opus-5-5", "codex.standard": "gpt-6.1-sol" },
  models: {
    "claude-opus-5-5": { display_name: "Opus 5.5", provider: "anthropic" }, "claude-sonnet-5-5": { display_name: "Sonnet 5.5", provider: "anthropic" },
    "claude-haiku-5-5": { display_name: "Haiku 5.5", provider: "anthropic" }, "gpt-6.1-sol": { display_name: "GPT-6.1 Sol", provider: "openai" },
  },
};
const ses = (id: string, folder: string | null, at: number, extra: Partial<Session> = {}) =>
  ({ id, folder, title: id, created_at: at, activity_at: at, deleted: false, archived: false, harness: "builtin", settings: {}, ...extra }) as Session;

const subtitle = () => screen.getByTestId("new-session-subtitle").textContent;
const box = () => screen.getByLabelText("Describe a task") as HTMLTextAreaElement;
const select = (label: string) => screen.getByLabelText(label) as HTMLSelectElement;
const optionValues = (label: string) => Array.from(select(label).options).map((o) => o.value);
async function mount() {
  render(<NewSession />);
  await act(async () => {});
}

beforeEach(() => {
  localStorage.clear();
  api.name = "Arshia J.";
  api.status = { installed: true, logged_in: true };
  useStore.setState({ appState: APP_STATE, sessions: [], currentId: null, draftGroup: null, messages: {}, paging: {}, skillChips: {}, drafts: {}, toast: null });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("NewSession", () => {
  it.each([false, true])("recovers a failed first message with its skill (history also fails=%s)", async (historyFails) => {
    const s = ses("s9", null, 1, { harness: "claude_code" });
    post.mockResolvedValueOnce(s).mockRejectedValueOnce(new Error("Message failed"));
    if (historyFails) get.mockRejectedValueOnce(new Error("History unavailable"));
    const result = await sessionActions.start({ text: "Keep my task\nwith details", skill: "graphify", folder: null, model: "claude-opus-5-5", effort: "medium", mode: "ask" });
    expect(result).toBe(false);
    expect(useStore.getState().currentId).toBe("s9");
    expect(useStore.getState().sessions).toContainEqual(s);
    expect(useStore.getState().toast?.text).toBe("Message failed");
    expect(useStore.getState().skillChips.s9).toBe("graphify");
    // Queued attachments still work alongside the recovered text.
    actions.attachToChat("s9", { path: "/tmp/notes.txt", name: "notes.txt", mime: "text/plain", text: "file content" });
    render(<Composer session={s} running={false} />);
    await act(async () => {});
    expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe("Keep my task\nwith details");
    expect(screen.getByLabelText("Remove notes.txt")).toBeTruthy();
    expect(useStore.getState().drafts.s9).toEqual([]);
    expect(screen.getByLabelText("Remove skill graphify")).toBeTruthy();
  });

  it("treats an empty first-message response as success", async () => {
    post.mockResolvedValueOnce(ses("s9", null, 1, { harness: "claude_code" })).mockResolvedValueOnce("");
    expect(await sessionActions.start({ text: "Hello", folder: null, model: "claude-opus-5-5", effort: "medium", mode: "ask" })).toBe(true);
    expect(useStore.getState().currentId).toBe("s9");
    expect(useStore.getState().drafts.s9).toBeUndefined();
  });

  it("keeps the message after creation fails and resets a missing folder to Chat only", async () => {
    localStorage.setItem("newSession.prefs", JSON.stringify({ location: "folder", folder: "/gone", model: "claude-sonnet-5-5", effort: "high", mode: "plan" }));
    post.mockRejectedValueOnce(Object.assign(new Error("Folder not found: /gone"), { status: 400 }));
    await mount();
    await act(async () => { fireEvent.change(box(), { target: { value: "Keep this task" } }); });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Send" })); });
    expect(box().value).toBe("Keep this task");
    expect(select("Location").value).toBe("chat");
    expect(subtitle()).toContain("Chat only");
    expect(JSON.parse(localStorage.getItem("newSession.prefs")!)).toEqual({ location: "chat", folder: null, model: "claude-sonnet-5-5", effort: "high", mode: "plan" });
    expect(useStore.getState().currentId).toBeNull();
    expect(post).toHaveBeenCalledTimes(1);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Send" })); });
    expect(post).toHaveBeenNthCalledWith(2, "/sessions", expect.objectContaining({ folder: null }));
  });

  it("clears a missing group so the same draft can be retried", async () => {
    useStore.setState({ draftGroup: "gone" });
    post.mockRejectedValueOnce(Object.assign(new Error("No such group"), { status: 400 }));
    await mount();
    await act(async () => { fireEvent.change(box(), { target: { value: "Keep this task" } }); });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Send" })); });
    expect(box().value).toBe("Keep this task");
    expect(useStore.getState().draftGroup).toBeNull();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Send" })); });
    expect(post.mock.calls[1][1]).not.toHaveProperty("group_id");
  });

  it("doesn't reset folder or group preferences for other creation errors", async () => {
    useStore.setState({ draftGroup: "g1" });
    localStorage.setItem("newSession.prefs", JSON.stringify({ location: "folder", folder: "/kept" }));
    post.mockRejectedValueOnce(Object.assign(new Error("Folder not found upstream"), { status: 500 }));
    await mount();
    await act(async () => { fireEvent.change(box(), { target: { value: "Keep this task" } }); });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Send" })); });
    expect(select("Location").value).toBe("folder");
    expect(useStore.getState().draftGroup).toBe("g1");
    expect(box().value).toBe("Keep this task");
  });

  it("greets by first name and last initial and shows the composer controls", async () => {
    await mount();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("What should we work on, Arshia J.?");
    expect(box().placeholder).toContain("type / for commands and skills");
    expect(select("Location").value).toBe("chat");
    // Claude models only, with tier labels; Opus (the orchestrator's model) by default.
    expect(optionValues("Model")).toEqual(["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]);
    expect(select("Model").selectedOptions[0].textContent).toBe("Opus 5.5 · claude.deep");
    expect(select("Effort").value).toBe("medium");
    // GDW's modes only: no bypass.
    expect(optionValues("Permission mode")).toEqual(["plan", "ask", "accept_edits"]);
    expect(select("Permission mode").value).toBe("ask");
    expect(screen.getByRole("button", { name: "Tools" })).toBeTruthy();
    expect((screen.getByRole("button", { name: "Send" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByLabelText("Attach files")).toBeNull();
    expect(screen.queryByTestId("claude-status-notice")).toBeNull();
    // Tools opens the skills chooser.
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Tools" })); });
    expect(screen.getByRole("dialog", { name: "Use a skill" }).textContent).toContain("graphify");
  });

  it("falls back to a plain greeting without a name", async () => {
    api.name = null;
    await mount();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("What should we work on?");
  });

  it("switches between Chat only and Folder", async () => {
    await mount();
    expect(subtitle()).toBe("Chat only: no folder; Claude Code works in a private scratch folder.");
    expect(screen.queryByTestId("folder-chip")).toBeNull();
    await act(async () => { fireEvent.change(select("Location"), { target: { value: "folder" } }); });
    expect(pickFolder).toHaveBeenCalled(); // no folder yet: the folder picker opens
    expect(subtitle()).toBe("The project stays in Forklift. Claude Code reads, edits and runs commands there.");
    expect(screen.getByTestId("folder-chip").textContent).toBe("Forklift");
    // The chip opens the picker again.
    pickFolder.mockResolvedValueOnce("/Users/me/Games/Apiva");
    await act(async () => { fireEvent.click(screen.getByTestId("folder-chip")); });
    expect(screen.getByTestId("folder-chip").textContent).toBe("Apiva");
    await act(async () => { fireEvent.change(select("Location"), { target: { value: "chat" } }); });
    expect(subtitle()).toContain("Chat only");
    expect(screen.queryByTestId("folder-chip")).toBeNull();
  });

  it("lists recent folders as chips; clicking one selects it", async () => {
    useStore.setState({ sessions: [ses("a", "/Users/me/SHAY_PC_rework", 30), ses("b", "/Users/me/Apiva", 20), ses("c", "/Users/me/SHAY_PC_rework", 10),
      ses("d", null, 40), ses("e", "/Users/me/Old", 50, { deleted: true })] });
    await mount();
    const chips = screen.getByRole("group", { name: "Recent folders" }).querySelectorAll("button");
    expect(Array.from(chips).map((c) => c.textContent)).toEqual(["SHAY_PC_rework", "Apiva"]);
    expect(chips[1].getAttribute("aria-pressed")).toBe("false");
    await act(async () => { fireEvent.click(chips[1]); });
    expect(chips[1].getAttribute("aria-pressed")).toBe("true");
    expect(select("Location").value).toBe("folder");
    expect(subtitle()).toContain("The project stays in Apiva.");
    expect(screen.getByTestId("new-session-subtitle").querySelector("[title]")?.getAttribute("title")).toBe("~/Apiva");
    expect(pickFolder).not.toHaveBeenCalled();
  });

  it("sends: creates a claude_code session with the chosen folder, model, effort and mode, then the message", async () => {
    useStore.setState({ sessions: [ses("a", "/Users/me/Apiva", 30, { group_id: "g1" } as any)], draftGroup: "g1" });
    await mount();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Apiva" })); });
    fireEvent.change(select("Model"), { target: { value: "claude-sonnet-5-5" } });
    fireEvent.change(select("Effort"), { target: { value: "high" } });
    fireEvent.change(select("Permission mode"), { target: { value: "accept_edits" } });
    await act(async () => { fireEvent.change(box(), { target: { value: "Fix the double jump" } }); });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Send" })); });
    expect(post).toHaveBeenNthCalledWith(1, "/sessions", { harness: "claude_code", folder: "/Users/me/Apiva", model: "claude-sonnet-5-5",
      effort: "high", mode: "accept_edits", group_id: "g1" });
    expect(post).toHaveBeenNthCalledWith(2, "/sessions/s9/messages", { text: "Fix the double jump", attachments: [] });
    expect(useStore.getState().currentId).toBe("s9");
    expect(useStore.getState().draftGroup).toBeNull();
  });

  it("sends a chat-only session with Enter, and /model changes the screen's model", async () => {
    await mount();
    await act(async () => { fireEvent.change(box(), { target: { value: "/model claude.fast" } }); });
    await act(async () => { fireEvent.keyDown(box(), { key: "Enter" }); });
    expect(select("Model").value).toBe("claude-haiku-5-5");
    await act(async () => { fireEvent.change(box(), { target: { value: "Hello there" } }); });
    await act(async () => { fireEvent.keyDown(box(), { key: "Enter" }); });
    expect(post).toHaveBeenCalledWith("/sessions", { harness: "claude_code", folder: null, model: "claude-haiku-5-5", effort: "medium", mode: "ask" });
    expect(post).toHaveBeenCalledWith("/sessions/s9/messages", { text: "Hello there", attachments: [] });
  });

  it("shows the login notice when Claude Code is logged out", async () => {
    api.status = { installed: true, logged_in: false };
    await mount();
    expect(screen.getByTestId("claude-status-notice").textContent).toContain("Claude Code isn't logged in: run claude auth login");
    api.status = { installed: true, logged_in: true };
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Retry" })); });
    expect(get).toHaveBeenCalledWith("/claude-code/status?refresh=1");
    expect(screen.queryByTestId("claude-status-notice")).toBeNull();
  });
});

describe("recentFolders", () => {
  it("keeps each folder once, newest first, without Trash", () => {
    expect(recentFolders([ses("a", "/x", 1), ses("b", "/y", 3), ses("c", "/x", 5), ses("d", "/z", 9, { deleted: true }), ses("e", null, 7)]))
      .toEqual(["/x", "/y"]);
  });
});
