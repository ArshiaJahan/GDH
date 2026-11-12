// Claude Code sessions in the UI: the harness option (new-session flow and Environment card), the
// session header chip with the `claude --resume` command, and the "log in" card's Retry.
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn(async () => ({ started: true })));
const toast = vi.hoisted(() => vi.fn());
const loginMessages = vi.hoisted(() => [
  { id: "old", meta: { error_kind: "claude_login" } }, { id: "m1", meta: { error_kind: "claude_login" } },
]);
vi.mock("../lib/api", () => ({ get, post }));
vi.mock("../lib/store", () => ({ actions: { toast }, useStore: (sel: (s: any) => unknown) => sel({ currentId: "s1", messages: { s1: loginMessages } }) }));

import { ClaudeCodeChip, ClaudeLoginNotice, HarnessSelect, HARNESSES } from "./ClaudeCode";

afterEach(() => { cleanup(); get.mockReset(); post.mockClear(); toast.mockClear(); });

describe("HarnessSelect", () => {
  it("offers Claude Code (subscription) and picks it", () => {
    const onChange = vi.fn();
    render(<HarnessSelect value="builtin" onChange={onChange} available={{ builtin: true, agent_sdk: false, codex_cli: true, claude_code: true }} />);
    const opt = screen.getByRole("option", { name: "Claude Code (subscription)" }) as HTMLOptionElement;
    expect(opt.value).toBe("claude_code");
    expect(opt.disabled).toBe(false);
    expect(opt.title).toContain("your own Claude login");
    fireEvent.change(screen.getByLabelText("Harness"), { target: { value: "claude_code" } });
    expect(onChange).toHaveBeenCalledWith("claude_code");
    expect(HARNESSES.map(([v]) => v)).toEqual(["builtin", "agent_sdk", "codex_cli", "claude_code"]);
  });

  it("marks it not installed when the CLI is missing", () => {
    render(<HarnessSelect value="builtin" onChange={vi.fn()} available={{ builtin: true, claude_code: false }} />);
    const opt = screen.getByRole("option", { name: "Claude Code (subscription) (not installed)" }) as HTMLOptionElement;
    expect(opt.disabled).toBe(true);
  });
});

describe("ClaudeCodeChip", () => {
  it("shows the login status and copies claude --resume <id>", async () => {
    get.mockResolvedValue({ installed: true, logged_in: true, auth_method: "claude.ai", bills_api: false });
    const writeText = vi.fn(async () => {});
    Object.assign(navigator, { clipboard: { writeText } });
    const id = "12345678-1234-1234-1234-123456789abc";
    render(<ClaudeCodeChip s={{ id: "s1", harness: "claude_code", settings: { claude_code_session: id } } as any} />);
    await act(async () => {});
    const chip = screen.getByTestId("claude-code-chip");
    expect(chip.textContent).toContain("Logged in (claude.ai)");
    expect(chip.textContent).toContain(`claude --resume ${id}`);
    await act(async () => { fireEvent.click(screen.getByLabelText("Copy the claude --resume command")); });
    expect(writeText).toHaveBeenCalledWith(`claude --resume ${id}`);
  });

  it("says when it isn't logged in", async () => {
    get.mockResolvedValue({ installed: true, logged_in: false, auth_method: "none" });
    render(<ClaudeCodeChip s={{ id: "s1", harness: "claude_code", settings: {} } as any} />);
    await act(async () => {});
    expect(screen.getByTestId("claude-code-chip").textContent).toContain("Not logged in");
  });

  it("hides the resume command for an invalid id", async () => {
    get.mockResolvedValue({ installed: true, logged_in: true });
    render(<ClaudeCodeChip s={{ id: "s1", settings: { claude_code_session: "abc; echo unsafe" } } as any} />);
    await act(async () => {});
    expect(screen.queryByLabelText("Copy the claude --resume command")).toBeNull();
  });
});

describe("ClaudeLoginNotice", () => {
  it("only offers Retry on the most recent login card", () => {
    render(<ClaudeLoginNotice m={{ id: "old", role: "assistant", content: [], meta: { error_kind: "claude_login" } }} />);
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
  });
  it("tells you to run claude auth login and retries", async () => {
    render(<ClaudeLoginNotice m={{ id: "m1", role: "assistant", content: [], meta: { error: true, error_kind: "claude_login" } }} />);
    expect(screen.getByRole("alert").textContent).toContain("claude auth login");
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Retry" })); });
    expect(post).toHaveBeenCalledWith("/claude-code/sessions/s1/retry", {});
    expect(toast).not.toHaveBeenCalled();
  });
});
