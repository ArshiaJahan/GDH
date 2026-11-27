import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const list = vi.hoisted(() => vi.fn());
const screenshot = vi.hoisted(() => vi.fn());
const folders = vi.hoisted(() => vi.fn());
const addFolder = vi.hoisted(() => vi.fn());
const removeFolder = vi.hoisted(() => vi.fn());
const pickFolder = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
const handlers = vi.hoisted(() => new Set<(e: any) => void>());
vi.mock("../lib/api", () => ({
  galleryApi: { list, screenshot, folders, addFolder, removeFolder },
  galleryMediaUrl: (e: { url: string | null }) => (e.url ? `http://x${e.url}&token=t` : null),
  inTauri: () => false,
  post,
}));
vi.mock("../lib/native", () => ({ pickFolder, revealInFinder: vi.fn(async () => true) }));
vi.mock("../lib/store", () => ({ actions: { toast: vi.fn(), onEvent: (cb: any) => { handlers.add(cb); return () => handlers.delete(cb); } } }));

import { GalleryTab, useGallery } from "./GalleryView";

function GalleryCard({ s }: { s: any }) {
  const g = useGallery(s.id);
  return <GalleryTab s={s} entries={g.entries} setEntries={g.setEntries} />;
}

const E = (o: any) => ({ kind: "image", path: "/p/a.png", url: "/api/gallery/file/i?session_id=s1", title: "a.png", created_at: 1, source: "tool", status: "done", ...o });
const session = { id: "s1", folder: "/p" } as any;

beforeEach(() => { folders.mockResolvedValue({ default: [], imported: [] }); });
afterEach(() => { cleanup(); vi.resetAllMocks(); vi.restoreAllMocks(); });

describe("Gallery tab", () => {
  it("renders items newest first, video badge, pending and failed cards", async () => {
    list.mockResolvedValue([
      E({ id: "p", status: "pending", url: null, prompt: "the boss room" }),
      E({ id: "v", kind: "video", title: "clip.mp4", url: "/api/gallery/file/v?session_id=s1" }),
      E({ id: "f", status: "failed", url: null, reason: "screenshot capture not implemented yet" }),
      E({ id: "i", title: "pic.png" }),
    ]);
    render(<GalleryCard s={session} />);
    expect(await screen.findByText("the boss room")).toBeTruthy();
    expect(screen.getByRole("status").textContent).toContain("the boss room");
    expect(screen.getByRole("alert").textContent).toContain("not implemented yet");
    expect(screen.getAllByTestId("play-badge")).toHaveLength(1);
    expect(screen.getByAltText("pic.png").getAttribute("loading")).toBe("lazy");
  });

  it("a failed screenshot offers its fix and a retry", async () => {
    list.mockResolvedValue([E({ id: "f", status: "failed", url: null, prompt: "castle scene 2 sec in",
      reason: "needs_harness: a batch screenshot needs the headless-ops harness editor scripts", actions: ["install_harness", "unknown"] })]);
    post.mockResolvedValue({ status: "pending" });
    screenshot.mockResolvedValue(E({ id: "n", status: "pending", url: null, prompt: "castle scene 2 sec in" }));
    render(<GalleryCard s={session} />);
    const card = await screen.findByRole("alert");
    expect(card.getAttribute("title")).toContain("needs_harness");
    expect(screen.queryByRole("button", { name: "unknown" })).toBeNull();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Install harness scripts" })); });
    expect(post).toHaveBeenCalledWith("/unity/actions/install_harness", { session_id: "s1" });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Retry" })); });
    expect(screenshot).toHaveBeenCalledWith("s1", "castle scene 2 sec in");
  });

  it("submits the prompt with Enter, disables the button when empty, and opens the lightbox", async () => {
    list.mockResolvedValue([E({ id: "i", prompt: "menu", title: "pic.png" })]);
    screenshot.mockResolvedValue(E({ id: "n", status: "pending", url: null, prompt: "hello" }));
    render(<GalleryCard s={session} />);
    await screen.findByAltText("pic.png");
    const btn = screen.getByRole("button", { name: "Take screenshot" }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    const box = screen.getByLabelText("Screenshot prompt") as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: "  hello " } });
    expect(btn.disabled).toBe(false);
    fireEvent.keyDown(box, { key: "Enter" });
    await waitFor(() => expect(screenshot).toHaveBeenCalledWith("s1", "hello"));
    expect(await screen.findByRole("status")).toBeTruthy();
    expect(box.value).toBe("");
    fireEvent.click(screen.getByLabelText("Open pic.png"));
    const dlg = screen.getByRole("dialog");
    expect(dlg.textContent).toContain("menu");
    expect(dlg.textContent).toContain("/p/a.png");
    expect(dlg.textContent).toContain("Open in Finder");
  });

  it("shows the route and framing a screenshot used in the lightbox, and the stage while pending", async () => {
    list.mockResolvedValue([
      E({ id: "w", status: "pending", url: null, prompt: "boss room", meta: { route: "mcp", route_label: "MCP for Unity", stage: "framing" } }),
      E({ id: "s", title: "cave", prompt: "player at the cave entrance", source: "screenshot", meta: {
        route: "raw_batch", route_label: "batch (unity.sh)", clone: true, notes: "low angle",
        camera: { cam_pos: [16, 0.3, -3], cam_rot: [-12.3456, 0, 0], used_fov: 60, used_scene: "Assets/Scenes/Cave.unity" } } }),
    ]);
    render(<GalleryCard s={session} />);
    expect((await screen.findByRole("status")).textContent).toContain("Framing · MCP for Unity");
    fireEvent.click(screen.getByLabelText("Open cave"));
    const line = screen.getByTestId("shot-route").textContent;
    expect(line).toContain("batch (unity.sh) · on a copy of the project · at 16, 0.3, -3 · rotation -12.35, 0, 0 · fov 60 · Assets/Scenes/Cave.unity");
    expect(screen.getByRole("dialog").textContent).toContain("low angle");
  });

  it("reloads on a gallery.updated event for its session", async () => {
    list.mockResolvedValue([]);
    render(<GalleryCard s={session} />);
    await screen.findByText("No media yet.");
    list.mockResolvedValue([E({ id: "i", title: "new.png" })]);
    await act(async () => { handlers.forEach((cb) => cb({ type: "gallery.updated", session_id: "s1", data: {} })); });
    expect(await screen.findByAltText("new.png")).toBeTruthy();
  });

  it("filters generated media, folder files and screenshots, and user uploads", async () => {
    const generated = E({ id: "g", title: "generated.png" });
    const shot = E({ id: "s", title: "requested.png", source: "screenshot" });
    const file = E({ id: "f", title: "folder.png", source: "folder", folder: "/p/Screenshots" });
    const user = E({ id: "u", title: "upload.png", source: "user" });
    list.mockImplementation(async (_sid, source) => {
      if (source === "generated") return [generated, shot];
      if (source === "folders") return [file];
      if (source === "user") return [user];
      return [generated, shot, file, user];
    });
    render(<GalleryCard s={session} />);
    expect(await screen.findByAltText("upload.png")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Generated" }));
    expect(screen.queryByAltText("upload.png")).toBeNull();
    expect(screen.getByAltText("generated.png")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Screenshots & folders" }));
    expect(screen.queryByAltText("generated.png")).toBeNull();
    expect(screen.getByAltText("requested.png")).toBeTruthy();
    expect(screen.getByAltText("folder.png")).toBeTruthy();
    expect(screen.getByText("Screenshots").getAttribute("title")).toBe("/p/Screenshots");
    fireEvent.click(screen.getByRole("button", { name: "Your uploads" }));
    expect(screen.queryByAltText("requested.png")).toBeNull();
    expect(screen.getByAltText("upload.png")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "All" }));
    expect(screen.getByAltText("generated.png")).toBeTruthy();
    await act(async () => {});
    expect(list).toHaveBeenCalledWith("s1", "generated");
    expect(list).toHaveBeenCalledWith("s1", "folders");
    expect(list).toHaveBeenCalledWith("s1", "user");
  });

  it("imports with the browser prompt fallback and removes an imported folder", async () => {
    list.mockResolvedValue([]);
    pickFolder.mockResolvedValue(null);
    const prompt = vi.spyOn(window, "prompt").mockReturnValue("/more/My captures");
    const folder = { path: "/more/My captures", exists: true, count: 3 };
    addFolder.mockImplementation(async () => { folders.mockResolvedValue({ default: [], imported: [folder] }); });
    removeFolder.mockImplementation(async () => { folders.mockResolvedValue({ default: [], imported: [] }); });
    render(<GalleryCard s={session} />);
    fireEvent.click(screen.getByRole("button", { name: "Import folder…" }));
    expect(await screen.findByText("My captures (3)")).toBeTruthy();
    expect(pickFolder).toHaveBeenCalled();
    expect(prompt).toHaveBeenCalledWith("Folder path");
    expect(addFolder).toHaveBeenCalledWith("s1", folder.path);
    fireEvent.click(screen.getByRole("button", { name: "Remove folder My captures" }));
    await waitFor(() => expect(screen.queryByText("My captures (3)")).toBeNull());
    expect(removeFolder).toHaveBeenCalledWith("s1", folder.path);
  });

  it("shows default folder counts and reloads media and counts on refresh and focus", async () => {
    list.mockResolvedValue([]);
    folders.mockResolvedValue({ imported: [], default: [
      { path: "/p/Logs/harness/screenshots", exists: true, count: 12 },
      { path: "/p/Recordings", exists: true, count: 3 },
    ] });
    render(<GalleryCard s={session} />);
    expect(await screen.findByText("Also showing: Logs/harness/screenshots (12), Recordings (3)")).toBeTruthy();
    list.mockResolvedValue([E({ id: "i", title: "new.png" })]);
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByAltText("new.png")).toBeTruthy();
    expect(list).toHaveBeenCalledWith("s1", undefined, true);
    list.mockResolvedValue([E({ id: "i", title: "newer.png" })]);
    fireEvent.focus(window);
    expect(await screen.findByAltText("newer.png")).toBeTruthy();
    expect(folders).toHaveBeenCalledTimes(3);
  });
});
