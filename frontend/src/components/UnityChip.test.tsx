// The Unity chip: the route label per state, the actions menu when the Editor is open without a
// bridge, cancel while busy, the session backend switch, and nothing outside Unity projects.
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn(async () => ({ status: "pending", message: "Approve in the chat" })));
const put = vi.hoisted(() => vi.fn());
const handlers = vi.hoisted(() => ({ list: [] as ((e: any) => void)[] }));
const toast = vi.hoisted(() => vi.fn());
const setState = vi.hoisted(() => vi.fn());
vi.mock("../lib/api", () => ({ get, post, put }));
vi.mock("../lib/store", () => ({
  actions: { toast, onEvent: (fn: (e: any) => void) => { handlers.list.push(fn); return () => { handlers.list = handlers.list.filter((x) => x !== fn); }; } },
  useStore: { setState },
}));

import { UnityChip } from "./UnityChip";

const STATE = {
  unity_project: true, mode: "mcp", route: "mcp", routes: { compile: "mcp", test: "mcp", build: "mcp", eval: "mcp" },
  editor_open: true, mcp_connected: true, reason: "Editor open, MCP connected", backend: "auto", backend_source: "global",
  session_backend: null, project_backend: null, global_backend: "auto", live: {}, cli: {}, actions: [], busy: null,
  pipeline_in_manifest: null, mcp_in_manifest: true,
};
const show = async (over: Record<string, unknown> = {}) => {
  get.mockResolvedValue({ ...STATE, ...over });
  render(<UnityChip sessionId="s1" />);
  await act(async () => {});
};

afterEach(() => { cleanup(); get.mockReset(); post.mockClear(); put.mockReset(); toast.mockClear(); setState.mockClear(); handlers.list = []; });

describe("UnityChip", () => {
  it.each([
    ["mcp", "Unity · MCP"], ["cli_live", "Unity · CLI live"], ["cli_batch", "Unity · CLI batch"], ["raw_batch", "Unity · Batch (unity.sh)"],
  ])("labels the %s route", async (route, text) => {
    await show({ route, editor_open: false });
    expect(screen.getByRole("button", { name: /^Unity:/ }).textContent).toBe(text);
    expect(get).toHaveBeenCalledWith("/unity/state?session_id=s1");
  });

  it("shows Safe Mode in red with its tooltip", async () => {
    await show({ route: "unavailable", live: { state: "safe_mode" } });
    const b = screen.getByRole("button", { name: "Unity: Safe Mode" });
    expect(b.textContent).toBe("Unity · Safe Mode");
    expect(b.title).toBe("compile errors at boot");
  });

  it("lists the recovery actions when the Editor is open without a bridge, and posts the chosen one", async () => {
    await show({ route: "unavailable", editor_open: true, reason: "No bridge", actions: ["install_pipeline", "close_editor"] });
    const b = screen.getByRole("button", { name: /Unity:/ });
    expect(b.textContent).toBe("Unity · Editor open — no bridge");
    fireEvent.click(b);
    expect(screen.getByRole("menuitem", { name: /Install Pipeline package/ })).toBeTruthy();
    await act(async () => { fireEvent.click(screen.getByRole("menuitem", { name: /Close Unity/ })); });
    expect(post).toHaveBeenCalledWith("/unity/actions/close_editor", { session_id: "s1" });
    expect(toast).toHaveBeenCalledWith("Approve in the chat", undefined);
  });

  it("offers running on a copy and posts use_clone", async () => {
    await show({ route: "unavailable", editor_open: true, reason: "No bridge", actions: ["install_pipeline", "use_mcp_once", "use_clone", "close_editor"] });
    fireEvent.click(screen.getByRole("button", { name: /Unity:/ }));
    expect(screen.getAllByRole("menuitem").map((m) => m.textContent)).toEqual([
      "Install Pipeline package (one-time, edits Packages/manifest.json)", "Use MCP for this check", "Run on a copy of the files",
      "Close Unity (exits without saving)"]);
    await act(async () => { fireEvent.click(screen.getByRole("menuitem", { name: "Run on a copy of the files" })); });
    expect(post).toHaveBeenCalledWith("/unity/actions/use_clone", { session_id: "s1" });
  });

  it("labels batch runs on a copy", async () => {
    await show({ route: "cli_batch", editor_open: true, clone: true, reason: "Unity has this project open: batch jobs run on a copy" });
    const b = screen.getByRole("button", { name: /Unity:/ });
    expect(b.textContent).toBe("Unity · CLI batch · on a copy");
    expect(b.title).toContain("on a copy");
  });

  it("offers install_harness whatever the route, and the upgrade wording when outdated", async () => {
    await show({ route: "raw_batch", editor_open: false, actions: ["install_harness"], harness: { installed: false, offer: true } });
    fireEvent.click(screen.getByRole("button", { name: /Unity:/ }));
    await act(async () => { fireEvent.click(screen.getByRole("menuitem", { name: /Install harness editor scripts/ })); });
    expect(post).toHaveBeenCalledWith("/unity/actions/install_harness", { session_id: "s1" });
    cleanup();
    await show({ route: "cli_batch", editor_open: false, actions: ["install_harness"],
      harness: { installed: true, version: 1, current_version: 2, outdated: true, offer: true } });
    fireEvent.click(screen.getByRole("button", { name: /Unity:/ }));
    expect(screen.getByRole("menuitem").textContent).toBe("Update harness editor scripts (version 1 → 2)");
  });

  it("is muted and action-less when unavailable with the Editor closed", async () => {
    await show({ route: "unavailable", editor_open: false, actions: ["install_pipeline"] });
    expect(screen.getByRole("button", { name: /Unity:/ }).textContent).toBe("Unity · unavailable");
    fireEvent.click(screen.getByRole("button", { name: /Unity:/ }));
    expect(screen.queryByRole("menuitem")).toBeNull();
  });

  it("shows the busy label and cancels the job, or opens the terminal", async () => {
    await show({ busy: { label: "compile", job_id: "j9" } });
    fireEvent.click(screen.getByRole("button", { name: "Unity: busy" }));
    expect(screen.getByRole("button", { name: "Unity: busy" }).textContent).toBe("Unity · busy: compile");
    fireEvent.click(screen.getByRole("menuitem", { name: "Show terminal" }));
    expect(setState).toHaveBeenCalledWith({ terminalOpen: true });
    fireEvent.click(screen.getByRole("button", { name: "Unity: busy" }));
    await act(async () => { fireEvent.click(screen.getByRole("menuitem", { name: "Cancel" })); });
    expect(post).toHaveBeenCalledWith("/unity/jobs/j9/cancel", {});
  });

  it("switches the session backend with PUT scope session", async () => {
    await show();
    put.mockResolvedValue({ ...STATE, session_backend: "cli" });
    fireEvent.click(screen.getByRole("button", { name: /Unity:/ }));
    await act(async () => { fireEvent.click(screen.getByLabelText("CLI")); });
    expect(put).toHaveBeenCalledWith("/unity/backend", { session_id: "s1", scope: "session", backend: "cli" });
    await act(async () => { fireEvent.click(screen.getByLabelText(/Project default/)); });
    expect(put).toHaveBeenLastCalledWith("/unity/backend", { session_id: "s1", scope: "session", backend: null });
  });

  it("updates from unity.state events for its session and closes on Escape", async () => {
    await show();
    act(() => handlers.list.forEach((h) => h({ type: "unity.state", session_id: "other", data: { ...STATE, route: "cli_live" } })));
    expect(screen.getByRole("button", { name: /Unity:/ }).textContent).toBe("Unity · MCP");
    act(() => handlers.list.forEach((h) => h({ type: "unity.state", session_id: "s1", data: { ...STATE, route: "cli_live" } })));
    expect(screen.getByRole("button", { name: /Unity:/ }).textContent).toBe("Unity · CLI live");
    fireEvent.click(screen.getByRole("button", { name: /Unity:/ }));
    expect(screen.getByRole("dialog")).toBeTruthy();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("renders nothing for non-Unity projects or when the fetch fails", async () => {
    await show({ unity_project: false });
    expect(document.body.querySelector("button")).toBeNull();
    cleanup();
    get.mockRejectedValue(new Error("404"));
    const { container } = render(<UnityChip sessionId="s2" />);
    await act(async () => {});
    expect(container.innerHTML).toBe("");
  });
});
