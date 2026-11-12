// Native glue for the desktop app (Tauri), with browser fallbacks.
//
// WKWebView ignores target=_blank and window.open, and cancels `<a download>` and attachment
// downloads, so in the app links go to the default browser (opener plugin) and downloads go
// through the `save_download` command (native save panel, then the shell streams the file
// from the backend). In the browser everything behaves as a normal web page.
//
// Backend URLs carry the session token (?token=), so in the app they never go to the default
// browser: local files open in their default app through the shell's `open_file` command
// (HTML opens in the browser as file://, without any token).

import { fileUrl, getConn, inTauri } from "./api";
import { actions } from "./store";

const errText = (e: unknown) => (e instanceof Error ? e.message : String(e));

/** Native folder picker in the app; a prompt in the browser. Returns null if cancelled, "" to clear. */
export async function pickFolder(current?: string): Promise<string | null> {
  if (inTauri()) {
    try {
      const { open } = await import("@tauri-apps/plugin-dialog");
      const r = await open({ directory: true, multiple: false, defaultPath: current });
      return typeof r === "string" ? r : null;
    } catch {
      /* fall through */
    }
  }
  const r = window.prompt("Folder path for this session (leave empty for chat only):", current ?? "~/");
  return r === null ? null : r.trim();
}

/** Reveal a file in Finder (app) — no-op in the browser. */
export async function revealInFinder(path: string): Promise<boolean> {
  if (!inTauri()) return false;
  try {
    const { revealItemInDir } = await import("@tauri-apps/plugin-opener");
    await revealItemInDir(path);
    return true;
  } catch {
    return false;
  }
}

/** The backend origin (http://127.0.0.1:port), or "" before the app is connected. */
function backendOrigin(): string {
  try {
    return new URL(getConn().base).origin;
  } catch {
    return "";
  }
}

/** Whether a URL points at the backend's API or carries its token: never for the default browser. */
export function isBackendUrl(url: string): boolean {
  let u: URL;
  try { u = new URL(url, location.href); } catch { return false; }
  const { token } = getConn();
  if (u.searchParams.has("token") || (token && url.includes(token))) return true;
  const backend = backendOrigin();
  return !!backend && u.origin === backend && u.pathname.startsWith("/api/");
}

/**
 * Open a local file the backend serves (artifacts, attachments, session files).
 * App: its default app via the shell (`open_file`; HTML in the default browser as file://, no
 * token); types that could run code are revealed in Finder instead. Browser: a new tab.
 */
export async function openLocalFile(path: string): Promise<void> {
  if (!inTauri()) {
    window.open(fileUrl(path), "_blank", "noopener,noreferrer");
    return;
  }
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    await invoke("open_file", { path });
  } catch (e) {
    if (errText(e) === "not_openable" && (await revealInFinder(path))) {
      actions.toast("Shown in Finder: Workspace doesn't open this file type directly.");
      return;
    }
    actions.toast(`Couldn't open the file: ${errText(e)}`, "error");
  }
}

/** Open a link in the default browser (app) or a new tab (browser). */
export async function openExternal(url: string): Promise<void> {
  if (inTauri()) {
    if (isBackendUrl(url)) {
      // Never hand the token to another app. A backend file link opens the file itself.
      const u = new URL(url, location.href);
      const path = u.pathname === "/api/file" ? u.searchParams.get("path") : null;
      if (path) await openLocalFile(path);
      else actions.toast("That link only works inside Workspace.", "error");
      return;
    }
    try {
      const { openUrl } = await import("@tauri-apps/plugin-opener");
      await openUrl(url);
    } catch (e) {
      actions.toast(`Couldn't open the link: ${errText(e)}`, "error");
    }
    return;
  }
  window.open(url, "_blank", "noopener,noreferrer");
}

/**
 * Download from the backend. `apiPath` is relative to /api, e.g. "/usage/export.csv?since=1".
 * App: native save panel, then the shell writes the file there. Browser: a normal download.
 */
export async function downloadFile(apiPath: string, suggestedName: string): Promise<void> {
  if (inTauri()) {
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      const saved = await invoke<string | null>("save_download", { path: `/api${apiPath}`, filename: suggestedName });
      if (saved) actions.toast(`Saved to ${saved}`);
    } catch (e) {
      actions.toast(`Download failed: ${errText(e)}`, "error");
    }
    return;
  }
  const { base, token } = getConn();
  const a = document.createElement("a");
  a.href = `${base}/api${apiPath}${apiPath.includes("?") ? "&" : "?"}token=${encodeURIComponent(token)}`;
  a.download = suggestedName;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

/** Download a local file the backend serves (artifacts, media, attachments). */
export function downloadPath(path: string, name?: string): Promise<void> {
  return downloadFile(`/file?${new URLSearchParams({ path, download: "1" })}`, name ?? path.split("/").pop() ?? "download");
}

/**
 * Install once at startup.
 * - Everywhere: a file dropped outside a drop zone (the composer) is refused instead of
 *   navigating the window to it.
 * - App: link clicks the web view can't handle (target=_blank, other origins, download links,
 *   e.g. links in rendered markdown) go to openExternal / downloadFile.
 */
export function installNativeGuards(): void {
  const refuseFiles = (e: DragEvent) => {
    if (e.defaultPrevented || !e.dataTransfer?.types.includes("Files")) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "none";
  };
  window.addEventListener("dragover", refuseFiles);
  window.addEventListener("drop", (e) => { if (e.dataTransfer?.types.includes("Files")) e.preventDefault(); });
  if (!inTauri()) return;
  document.addEventListener("click", (e) => {
    if (e.defaultPrevented || e.button !== 0) return;
    const a = (e.target as Element | null)?.closest?.("a[href]") as HTMLAnchorElement | null;
    if (!a) return;
    let url: URL;
    try { url = new URL(a.href, location.href); } catch { return; }
    const download = a.hasAttribute("download") || url.searchParams.get("download") === "1";
    if (url.origin === location.origin && a.target !== "_blank" && !download) return; // in-app link
    const backend = backendOrigin();
    if (url.origin === backend && url.pathname.startsWith("/api/")) {
      e.preventDefault();
      if (download) {
        url.searchParams.delete("token"); // the shell authenticates itself
        const name = a.getAttribute("download") || url.searchParams.get("path")?.split("/").pop() || "download";
        void downloadFile(url.pathname.slice(4) + url.search, name);
      } else {
        void openExternal(url.href); // never reaches the browser: files open locally, see openExternal
      }
    } else if (["http:", "https:", "mailto:", "tel:"].includes(url.protocol)) {
      e.preventDefault();
      void openExternal(url.href);
    }
  }, true);
}
