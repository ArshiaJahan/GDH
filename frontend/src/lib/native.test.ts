// The backend token never reaches the default browser from the desktop app.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const BASE = "http://127.0.0.1:5555";
const TOKEN = "s3cr3t-token";

const tauri = vi.hoisted(() => ({ on: true }));
const openUrl = vi.hoisted(() => vi.fn(async (_url: string) => {}));
const revealItemInDir = vi.hoisted(() => vi.fn(async (_path: string) => {}));
const invoke = vi.hoisted(() => vi.fn(async (_cmd: string, _args?: unknown): Promise<unknown> => null));
const toast = vi.hoisted(() => vi.fn());

vi.mock("./api", () => ({
  getConn: () => ({ base: BASE, token: TOKEN }),
  inTauri: () => tauri.on,
  fileUrl: (path: string) => `${BASE}/api/file?${new URLSearchParams({ path, token: TOKEN })}`,
}));
vi.mock("./store", () => ({ actions: { toast } }));
vi.mock("@tauri-apps/plugin-opener", () => ({ openUrl, revealItemInDir }));
vi.mock("@tauri-apps/api/core", () => ({ invoke }));

import { installNativeGuards, isBackendUrl, openExternal, openLocalFile } from "./native";

const fileLink = (path: string, extra: Record<string, string> = {}) =>
  `${BASE}/api/file?${new URLSearchParams({ path, token: TOKEN, ...extra })}`;

beforeEach(() => {
  tauri.on = true;
  vi.clearAllMocks();
});
afterEach(() => {
  document.body.innerHTML = "";
});

describe("isBackendUrl", () => {
  it("flags backend API URLs and anything carrying the token", () => {
    expect(isBackendUrl(fileLink("/a/b.html"))).toBe(true);
    expect(isBackendUrl(`${BASE}/api/sessions`)).toBe(true);
    expect(isBackendUrl(`https://example.com/?token=x`)).toBe(true);
    expect(isBackendUrl(`https://example.com/#${TOKEN}`)).toBe(true);
    expect(isBackendUrl("https://example.com/docs")).toBe(false);
    expect(isBackendUrl("mailto:a@b.c")).toBe(false);
  });
});

describe("in the app", () => {
  it("opens backend file links locally, never in the browser", async () => {
    await openExternal(fileLink("/data/report.html"));
    expect(openUrl).not.toHaveBeenCalled();
    expect(invoke).toHaveBeenCalledWith("open_file", { path: "/data/report.html" });
  });

  it("refuses other backend URLs", async () => {
    await openExternal(`${BASE}/api/sessions?token=${TOKEN}`);
    expect(openUrl).not.toHaveBeenCalled();
    expect(invoke).not.toHaveBeenCalled();
    expect(toast).toHaveBeenCalled();
  });

  it("still opens ordinary links in the browser", async () => {
    await openExternal("https://example.com/docs");
    expect(openUrl).toHaveBeenCalledWith("https://example.com/docs");
  });

  it("reveals file types it won't open", async () => {
    invoke.mockRejectedValueOnce("not_openable");
    await openLocalFile("/data/run.command");
    expect(revealItemInDir).toHaveBeenCalledWith("/data/run.command");
    expect(openUrl).not.toHaveBeenCalled();
  });

  it("routes clicked backend file links (target=_blank) to open_file", async () => {
    installNativeGuards();
    const a = document.createElement("a");
    a.href = fileLink("/data/a.pdf");
    a.target = "_blank";
    a.textContent = "a.pdf";
    document.body.appendChild(a);
    a.click();
    await vi.waitFor(() => expect(invoke).toHaveBeenCalledWith("open_file", { path: "/data/a.pdf" }));
    expect(openUrl).not.toHaveBeenCalled();
  });
});

describe("in the browser", () => {
  it("keeps opening files in a new tab", async () => {
    tauri.on = false;
    const open = vi.spyOn(window, "open").mockImplementation(() => null);
    await openLocalFile("/data/report.html");
    expect(open).toHaveBeenCalledWith(fileLink("/data/report.html"), "_blank", "noopener,noreferrer");
    expect(invoke).not.toHaveBeenCalled();
  });
});
