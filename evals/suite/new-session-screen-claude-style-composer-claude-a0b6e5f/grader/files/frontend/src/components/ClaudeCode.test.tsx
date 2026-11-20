// Claude Code sessions in the UI: harness names (shown read-only), the new-session screen's login
// notice, the session header chip with the `claude --resume` command, and the "log in" card's Retry.
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

import { ClaudeCodeChip, ClaudeLoginNotice, ClaudeStatusNotice, harnessName, HARNESSES } from "./ClaudeCode";

afterEach(() => { cleanup(); get.mockReset(); post.mockClear(); toast.mockClear(); });

describe("harness names", () => {
  it("names Claude Code (subscription) and keeps unknown ids", () => {
    expect(HARNESSES.map(([v]) => v)).toEqual(["builtin", "agent_sdk", "codex_cli", "claude_code"]);
    expect(harnessName("claude_code")).toBe("Claude Code (subscription)");
    expect(harnessName("builtin")).toBe("Built-in loop");
    expect(harnessName("other")).toBe("other");
  });
});

describe("ClaudeStatusNotice", () => {
  it("says nothing while Claude Code is ready or still being checked", () => {
    const { container } = render(<><ClaudeStatusNotice st={null} retry={vi.fn()} />
      <ClaudeStatusNotice st={{ installed: true, logged_in: true } as any} retry={vi.fn()} /></>);
    expect(container.textContent).toBe("");
  });
  it("tells you to log in, copies the command and retries", async () => {
    const retry = vi.fn();
    const writeText = vi.fn(async () => {});
    Object.assign(navigator, { clipboard: { writeText } });
    render(<ClaudeStatusNotice st={{ installed: true, logged_in: false } as any} retry={retry} />);
    expect(screen.getByTestId("claude-status-notice").textContent).toContain("Claude Code isn't logged in: run claude auth login");
    await act(async () => { fireEvent.click(screen.getByLabelText("Copy claude auth login")); });
    expect(writeText).toHaveBeenCalledWith("claude auth login");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(retry).toHaveBeenCalled();
  });
  it("says when the CLI is missing", () => {
    render(<ClaudeStatusNotice st={{ installed: false, logged_in: false } as any} retry={vi.fn()} />);
    expect(screen.getByTestId("claude-status-notice").textContent).toContain("The claude CLI isn't installed");
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
    expect(chip.classList.contains("shrink")).toBe(true);
    expect(chip.classList.contains("min-w-0")).toBe(true);
    expect(chip.classList.contains("overflow-hidden")).toBe(true);
    expect(chip.classList.contains("shrink-0")).toBe(false);
    expect(chip.querySelector("code")?.classList.contains("min-[1500px]:inline")).toBe(true);
    expect(chip.querySelector("code")?.classList.contains("md:inline")).toBe(false);
    expect(screen.getByLabelText("Copy the claude --resume command").parentElement?.classList.contains("shrink-0")).toBe(true);
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
