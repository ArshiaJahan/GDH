// Accessibility and first-run UI: the Modal's focus handling, the "engine stopped" screen, the
// setup checklist and the no-key notice.
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const invoke = vi.hoisted(() => vi.fn(async (_cmd: string): Promise<unknown> => null));
const get = vi.hoisted(() => vi.fn(async (_p: string): Promise<unknown> => null));
const go = vi.hoisted(() => vi.fn());
vi.mock("@tauri-apps/api/core", () => ({ invoke }));
vi.mock("../lib/api", () => ({ inTauri: () => true, get }));
vi.mock("../lib/store", () => ({
  actions: { go, toast: vi.fn() },
  useStore: (sel: (s: any) => unknown) => sel({ appState: { tiers: {}, models: {} }, sessions: [] }),
}));

import { Modal } from "./ui";
import { EngineStopped, isBackendExit } from "./SystemNotices";
import { NoKeyNotice, SetupChecklist } from "./SetupChecklist";

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
});
afterEach(cleanup);

describe("Modal", () => {
  it("is a labelled modal dialog, focuses its first field, traps Tab and restores focus", () => {
    const opener = document.createElement("button");
    opener.textContent = "open";
    document.body.appendChild(opener);
    opener.focus();
    const onClose = vi.fn();
    const { unmount } = render(
      <Modal title="Rename" onClose={onClose}>
        <input aria-label="Name" />
        <button>Save</button>
      </Modal>,
    );
    const dialog = screen.getByRole("dialog", { name: "Rename" });
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    const input = screen.getByLabelText("Name");
    expect(document.activeElement).toBe(input);
    // Tab from the last control wraps to the first (the Close button), Shift+Tab from the first wraps back.
    const save = screen.getByText("Save");
    save.focus();
    fireEvent.keyDown(window, { key: "Tab" });
    expect(document.activeElement).toBe(screen.getByText("Close"));
    fireEvent.keyDown(window, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(save);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
    unmount();
    expect(document.activeElement).toBe(opener);
    opener.remove();
  });

  it("without a field, focuses the dialog itself; only the topmost dialog closes on Esc", () => {
    const outer = vi.fn(), inner = vi.fn();
    render(
      <Modal title="Outer" onClose={outer}>
        <Modal title="Inner" onClose={inner}><p>hi</p></Modal>
      </Modal>,
    );
    expect(document.activeElement).toBe(screen.getByRole("dialog", { name: "Inner" }));
    fireEvent.keyDown(window, { key: "Escape" });
    expect(inner).toHaveBeenCalledTimes(1);
    expect(outer).not.toHaveBeenCalled();
  });
});

describe("EngineStopped", () => {
  const exit = { kind: "exited" as const, message: "GameDevWorkstation's engine stopped (exit code 1).", code: 1,
    log_path: "/Users/me/Library/Logs/GameDevWorkstation/backend-stdout.log", last_lines: "Traceback: boom" };

  it("recognises the shell's error and shows why, the log and Restart", async () => {
    expect(isBackendExit(exit)).toBe(true);
    expect(isBackendExit(new Error("x"))).toBe(false);
    const reload = vi.fn();
    vi.stubGlobal("location", { ...window.location, reload });
    render(<EngineStopped exit={exit} />);
    expect(screen.getByRole("alertdialog").textContent).toContain("GameDevWorkstation's engine stopped");
    expect(screen.getByText(exit.log_path)).toBeTruthy();
    expect(screen.getByText("Traceback: boom")).toBeTruthy();
    await act(async () => fireEvent.click(screen.getByText("Restart")));
    expect(invoke).toHaveBeenCalledWith("restart_backend");
    expect(reload).toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
});

describe("SetupChecklist", () => {
  it("lists what's left with a way to do it, and can be dismissed for good", async () => {
    get.mockResolvedValue({ keys: { anthropic: false, openai: true, elevenlabs: false }, folder: true, skill: false });
    render(<SetupChecklist />);
    await screen.findByRole("region", { name: "Getting started" });
    expect(screen.getByText("Add your Anthropic API key")).toBeTruthy();
    expect(screen.getByText("3 steps left")).toBeTruthy();
    fireEvent.click(screen.getAllByText("Settings → Accounts")[0]);
    expect(go).toHaveBeenCalledWith("settings", { section: "accounts" });
    fireEvent.click(screen.getByLabelText("Dismiss the getting started checklist"));
    expect(screen.queryByRole("region", { name: "Getting started" })).toBeNull();
    expect(localStorage.getItem("setupChecklistDismissed")).toBe("1");
  });

  it("is gone once the required steps are done (the optional keys don't keep it)", async () => {
    get.mockResolvedValue({ keys: { anthropic: true, openai: false, elevenlabs: false }, folder: true, skill: true });
    const { container } = render(<SetupChecklist />);
    await waitFor(() => expect(get).toHaveBeenCalledWith("/setup"));
    await act(async () => {});
    expect(container.textContent).toBe("");
  });
});

it("NoKeyNotice explains and opens Settings → Accounts", () => {
  render(<NoKeyNotice m={{ id: "m", role: "assistant", content: [], meta: { error: "no_key", provider: "anthropic" } } as any} />);
  expect(screen.getByRole("alert").textContent).toContain("Add your Anthropic key");
  fireEvent.click(screen.getByText("Open Settings → Accounts"));
  expect(go).toHaveBeenCalledWith("settings", { section: "accounts" });
});
