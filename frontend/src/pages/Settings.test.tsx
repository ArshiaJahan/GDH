// Settings fields that save themselves: numbers only once you're done typing (and when the page
// goes away), and allowlist rules only once they're complete.
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.hoisted(() => vi.fn(async (_p: string): Promise<any> => null));
vi.mock("../lib/api", () => ({ api: vi.fn(), del: vi.fn(), get, post: vi.fn() }));
vi.mock("../lib/store", () => ({ actions: { toast: vi.fn(), refreshState: vi.fn() }, useStore: (sel: (s: any) => unknown) => sel({ pageArgs: {} }) }));
vi.mock("../components/StorageSettings", () => ({ StorageSettings: () => null }));

import { Allowlist, ClaudeCodeSection, Num, savableAllowRules, UnitySettings, validAllowRule } from "./Settings";

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

const type = (el: HTMLElement, value: string) => fireEvent.change(el, { target: { value } });

describe("Num", () => {
  it("doesn't save half-typed values, only on blur or Enter", () => {
    const onSave = vi.fn();
    render(<Num value={50} onSave={onSave} label="Daily" />);
    const input = screen.getByLabelText("Daily");
    type(input, "5"); // on the way from 50 to 500
    act(() => { vi.advanceTimersByTime(5000); });
    type(input, "500");
    act(() => { vi.advanceTimersByTime(5000); });
    expect(onSave).not.toHaveBeenCalled();
    fireEvent.blur(input);
    expect(onSave).toHaveBeenCalledExactlyOnceWith(500);
    fireEvent.keyDown(input, { key: "Enter" }); // same value: no second save
    expect(onSave).toHaveBeenCalledTimes(1);
  });

  it("saves the typed value when it unmounts (navigating away)", () => {
    const onSave = vi.fn();
    const { unmount } = render(<Num value={4} onSave={onSave} label="Parallel" />);
    type(screen.getByLabelText("Parallel"), "6");
    unmount();
    expect(onSave).toHaveBeenCalledExactlyOnceWith(6);
  });

  it("doesn't save invalid or below-min values", () => {
    const onSave = vi.fn();
    const { unmount } = render(<Num value={4} min={1} onSave={onSave} label="Turns" />);
    const input = screen.getByLabelText("Turns");
    type(input, "");
    fireEvent.blur(input);
    type(input, "0");
    fireEvent.blur(input);
    unmount();
    expect(onSave).not.toHaveBeenCalled();
  });

  it("lets the same value be retried after a failed save", async () => {
    const onSave = vi.fn(async () => false);
    render(<Num value={10} onSave={onSave} label="Job" />);
    const input = screen.getByLabelText("Job");
    type(input, "20");
    fireEvent.blur(input);
    await act(async () => {});
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSave).toHaveBeenCalledTimes(2);
    expect(onSave).toHaveBeenLastCalledWith(20);
  });
});

describe("allowlist rules", () => {
  it("are complete only with a known kind and a non-empty pattern", () => {
    expect(validAllowRule("run_command:git status*")).toBe(true);
    expect(validAllowRule("mcp:github__get_*")).toBe(true);
    expect(validAllowRule("run_command:")).toBe(false);
    expect(validAllowRule("run_command:   ")).toBe(false);
    expect(validAllowRule("run_command")).toBe(false);
    expect(validAllowRule("bogus:x")).toBe(false);
    expect(validAllowRule(":x")).toBe(false);
    expect(savableAllowRules([" edit:* ", "run_command:", "", "delete:tmp/*"])).toEqual(["edit:*", "delete:tmp/*"]);
  });
});

describe("Allowlist", () => {
  it("never saves an incomplete rule, keeps it on screen, and saves it once complete", () => {
    const save = vi.fn();
    const { rerender } = render(<Allowlist rules={["edit:*"]} save={save} />);
    type(screen.getByLabelText("New allowlist rule"), "run_command:");
    fireEvent.click(screen.getByText("Add rule"));
    act(() => { vi.advanceTimersByTime(5000); });
    expect(save).not.toHaveBeenCalled(); // nothing complete changed
    expect((screen.getByLabelText("Allowlist rule 2") as HTMLInputElement).value).toBe("run_command:");
    expect(screen.getByText("Not saved until complete")).toBeTruthy();

    // Another edit saves the complete rules only; the saved list coming back keeps the draft row.
    type(screen.getByLabelText("Allowlist rule 1"), "edit:src/*");
    act(() => { vi.advanceTimersByTime(1000); });
    expect(save).toHaveBeenLastCalledWith(["edit:src/*"]);
    rerender(<Allowlist rules={["edit:src/*"]} save={save} />);
    expect((screen.getByLabelText("Allowlist rule 2") as HTMLInputElement).value).toBe("run_command:");

    type(screen.getByLabelText("Allowlist rule 2"), "run_command:git status*");
    act(() => { vi.advanceTimersByTime(1000); });
    expect(save).toHaveBeenLastCalledWith(["edit:src/*", "run_command:git status*"]);
    expect(screen.queryByText("Not saved until complete")).toBeNull();
  });

  it("keeps an incomplete row when the saved list changes elsewhere", () => {
    const save = vi.fn();
    const { rerender } = render(<Allowlist rules={["edit:*"]} save={save} />);
    type(screen.getByLabelText("New allowlist rule"), "mcp:");
    fireEvent.click(screen.getByText("Add rule"));
    rerender(<Allowlist rules={["edit:*", "delete:tmp/*"]} save={save} />);
    const values = screen.getAllByLabelText(/^Allowlist rule/).map((x) => (x as HTMLInputElement).value);
    expect(values).toEqual(["edit:*", "delete:tmp/*", "mcp:"]);
    expect(save).not.toHaveBeenCalled();
  });
});

describe("UnitySettings", () => {
  it("shows the detected CLI and editors, and saves the chosen backend", async () => {
    vi.useRealTimers();
    get.mockImplementation(async (p: string) => p === "/unity/info"
      ? { cli: { path: "/usr/local/bin/unity", version: "1.2.3", ok: true, update_available: "1.3.0" },
          editors: [{ version: "6000.0.1f1", architecture: "arm64", location: "/Applications/Unity/Hub/Editor/6000.0.1f1" }], config: {} }
      : null);
    const save = vi.fn();
    render(<UnitySettings st={{ unity: { backend: "auto", eval: "ask" } }} save={save} />);
    await act(async () => {});
    expect(screen.getByTestId("unity-cli").textContent).toContain("1.2.3");
    expect(screen.getByTestId("unity-cli").textContent).toContain("update available: 1.3.0");
    expect(screen.getByText("6000.0.1f1")).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: "CLI" }));
    expect(save).toHaveBeenCalledWith({ unity: { backend: "cli" } }, "Default backend");
    fireEvent.change(screen.getByLabelText("Eval policy"), { target: { value: "off" } });
    expect(save).toHaveBeenLastCalledWith({ unity: { eval: "off" } }, "Eval policy");
  });

  it("saves the clone-when-open and harness script policies", async () => {
    vi.useRealTimers();
    get.mockImplementation(async () => ({ cli: {}, editors: [], config: {} }));
    const save = vi.fn();
    render(<UnitySettings st={{ unity: { clone_when_open: "ask", harness_scripts: "ask", harness_git_exclude: true } }} save={save} />);
    await act(async () => {});
    expect((screen.getByLabelText("Run on a copy") as HTMLSelectElement).value).toBe("ask");
    fireEvent.change(screen.getByLabelText("Run on a copy"), { target: { value: "always" } });
    expect(save).toHaveBeenLastCalledWith({ unity: { clone_when_open: "always" } }, "Run on a copy");
    fireEvent.change(screen.getByLabelText("Harness editor scripts"), { target: { value: "never" } });
    expect(save).toHaveBeenLastCalledWith({ unity: { harness_scripts: "never" } }, "Harness editor scripts");
    fireEvent.click(screen.getByLabelText("Keep harness scripts out of git"));
    expect(save).toHaveBeenLastCalledWith({ unity: { harness_git_exclude: false } }, "Keep harness scripts out of git");
  });

  it("says when the CLI is missing", async () => {
    vi.useRealTimers();
    get.mockImplementation(async () => ({ cli: {}, editors: [], config: {} }));
    render(<UnitySettings st={{ unity: {} }} save={vi.fn()} />);
    await act(async () => {});
    expect(screen.getByTestId("unity-cli").textContent).toContain("Not found");
  });
});

describe("ClaudeCodeSection", () => {
  const STATUS = { installed: true, path: "/opt/homebrew/bin/claude", version: "2.1.308 (Claude Code)", logged_in: false,
    auth_method: "none", auth: { loggedIn: false }, bills_api: false, error: null, login_hint: "" };

  it("shows the detected CLI and login status, and saves its settings", async () => {
    vi.useRealTimers();
    get.mockImplementation(async (p: string) => (p.startsWith("/claude-code/status") ? STATUS : null));
    const save = vi.fn(async () => true);
    render(<ClaudeCodeSection st={{ claude_code: { cli_path: "", load_user_mcp: false, setting_sources: "" } }} save={save} />);
    await act(async () => {});
    expect(get).toHaveBeenCalledWith("/claude-code/status");
    expect(screen.getByTestId("claude-cli").textContent).toContain("/opt/homebrew/bin/claude");
    expect(screen.getByTestId("claude-cli").textContent).toContain("2.1.308");
    expect(screen.getByTestId("claude-login").textContent).toBe("Not logged in");
    expect(screen.getByText("claude auth login")).toBeTruthy();
    const sources = screen.getByLabelText("Claude Code setting sources") as HTMLSelectElement;
    expect(sources.value).toBe("");
    fireEvent.change(sources, { target: { value: "user" } });
    expect(save).toHaveBeenLastCalledWith({ claude_code: { setting_sources: "user" } }, "Settings files");
    fireEvent.click(screen.getByLabelText("Load my Claude Code MCP servers"));
    expect(save).toHaveBeenLastCalledWith({ claude_code: { load_user_mcp: true } }, "Your MCP servers");
    const path = screen.getByLabelText("claude CLI path");
    fireEvent.change(path, { target: { value: "/usr/local/bin/claude" } });
    await act(async () => { fireEvent.blur(path); });
    expect(save).toHaveBeenCalledWith({ claude_code: { cli_path: "/usr/local/bin/claude" } }, "CLI path");
    expect(get).toHaveBeenLastCalledWith("/claude-code/status?refresh=1"); // re-checked after the new path
  });

  it("says when the CLI is missing", async () => {
    vi.useRealTimers();
    get.mockImplementation(async () => ({ ...STATUS, installed: false, path: null, version: null, error: "The claude CLI wasn't found" }));
    render(<ClaudeCodeSection st={{ claude_code: {} }} save={vi.fn()} />);
    await act(async () => {});
    expect(screen.getByTestId("claude-cli").textContent).toContain("wasn't found");
    expect(screen.getByTestId("claude-login").textContent).toBe("claude CLI not found");
  });
});
