// The composer's slash commands: /task (task board) and /workflow (chains) side by side.
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const get = vi.hoisted(() => vi.fn(async (path: string): Promise<any> => (path === "/skills" ? { skills: [] } : [])));
const post = vi.hoisted(() => vi.fn(async (_path: string, _body?: unknown): Promise<any> => ({ code: "Task00007", column: "Backlog" })));
vi.mock("../lib/api", () => ({ get, post, patch: vi.fn(), upload: vi.fn() }));
const chains = vi.hoisted(() => vi.fn(async () => ({
  templates: [{ id: "bugfix", title: "Bug fix", summary: "repro, fix, verify", kinds: ["chain", "campaign"], phases: [{ name: "Repro" }, { name: "Fix" }] }],
  errors: [],
})));
const create = vi.hoisted(() => vi.fn(async () => ({})));
vi.mock("../lib/campaigns", async (orig) => ({ ...(await orig<any>()), campaignsApi: { chains, create } }));
const toast = vi.hoisted(() => vi.fn());
vi.mock("../lib/store", () => ({
  actions: { toast, setSkillChip: vi.fn(), go: vi.fn(), onEvent: () => () => {} },
  useStore: (sel: (s: any) => unknown) => sel({ appState: { tiers: {}, models: {} }, drafts: {}, skillChips: {} }),
}));

import { Composer } from "./Composer";

const SESSION = { id: "s1", folder: "/p/game", mode: "accept_edits", model: "m", settings: {} } as any;
const box = () => screen.getByRole("textbox") as HTMLTextAreaElement;
const type = async (text: string) => { await act(async () => { fireEvent.change(box(), { target: { value: text } }); }); };
const options = () => screen.queryAllByRole("option").map((o) => o.textContent ?? "");

afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("Composer slash commands", () => {
  it.each([false, true])("hides workflows and explains /workflow for Claude subscription sessions (draft=%s)", async (draft) => {
    render(<Composer session={{ ...SESSION, harness: "claude_code" }} running={false}
      draft={draft ? { set: vi.fn(), start: vi.fn(), rows: [null, null], placeholder: "Task" } : undefined} />);
    await act(async () => {});
    expect(chains).not.toHaveBeenCalled();
    await type("/");
    expect(options().some((o) => o.startsWith("/workflow"))).toBe(false);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: draft ? "Tools" : "Use a skill" })); });
    expect(screen.getByRole("dialog", { name: "Use a skill" }).textContent).not.toContain("Bug fix");
    fireEvent.keyDown(document, { key: "Escape" });
    await type("/workflow bugfix fix it");
    await act(async () => { fireEvent.keyDown(box(), { key: "Enter" }); });
    expect(toast).toHaveBeenCalledWith("Workflows run on the built-in loop with an API key, so they aren't available in Claude subscription sessions.", "error");
    expect(create).not.toHaveBeenCalled();
    expect(post).not.toHaveBeenCalled();
  });

  it("offers /task and /workflow, completes both and runs /task", async () => {
    render(<Composer session={SESSION} running={false} />);
    await act(async () => {});
    expect(chains).toHaveBeenCalledWith("/p/game", "chain");
    await type("/");
    expect(options().some((o) => o.startsWith("/task"))).toBe(true);
    expect(options().some((o) => o.startsWith("/workflow"))).toBe(true);
    // /task: its subcommands
    await type("/task ");
    expect(options().some((o) => o.startsWith("new"))).toBe(true);
    // /workflow: the folder's workflows; Tab attaches the chip
    await type("/workflow b");
    expect(options()[0]).toContain("bugfix");
    await act(async () => { fireEvent.keyDown(box(), { key: "Tab" }); });
    expect(screen.getByText(/Workflow: Bug fix/)).toBeTruthy();
    await act(async () => { fireEvent.click(screen.getByLabelText("Remove workflow Bug fix")); });
    // /task new runs on Enter
    await type("/task new Fix the double jump #player");
    await act(async () => { fireEvent.keyDown(box(), { key: "Enter" }); });
    expect(post).toHaveBeenCalledWith("/tasks/items", expect.objectContaining({ title: "Fix the double jump", labels: ["player"] }));
    expect(create).not.toHaveBeenCalled();
  });

  it("starts a workflow from /workflow <id> <request>", async () => {
    render(<Composer session={SESSION} running={false} />);
    await act(async () => {});
    await type("/workflow bugfix the jump double-fires");
    await act(async () => { fireEvent.keyDown(box(), { key: "Enter" }); });
    expect(create).toHaveBeenCalledWith({ template: "bugfix", kind: "chain", session_id: "s1", request: "the jump double-fires" });
    expect(post).toHaveBeenCalledWith("/sessions/s1/messages", expect.objectContaining({ text: "Run the Bug fix workflow.\n\nthe jump double-fires" }));
  });
});
