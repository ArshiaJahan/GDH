import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const list = vi.hoisted(() => vi.fn());
const screenshot = vi.hoisted(() => vi.fn());
const handlers = vi.hoisted(() => ({ cb: null as null | ((e: any) => void) }));
vi.mock("../../lib/api", () => ({
  galleryApi: { list, screenshot },
  galleryMediaUrl: (e: { url: string | null }) => (e.url ? `http://x${e.url}&token=t` : null),
}));
vi.mock("../../lib/native", () => ({ revealInFinder: vi.fn(async () => true) }));
vi.mock("../../lib/store", () => ({ actions: { toast: vi.fn(), onEvent: (cb: any) => { handlers.cb = cb; return () => {}; } } }));
vi.mock("../SidePanel", () => ({ Card: ({ title, children }: { title: string; children: ReactNode }) => <div><h2>{title}</h2>{children}</div> }));

import { GalleryCard } from "./GalleryCard";

const E = (o: any) => ({ kind: "image", path: "/p/a.png", url: "/api/gallery/file/i?session_id=s1", title: "a.png", created_at: 1, source: "tool", status: "done", ...o });
const session = { id: "s1" } as any;

afterEach(() => { cleanup(); list.mockReset(); screenshot.mockReset(); });

describe("GalleryCard", () => {
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
    await act(async () => { handlers.cb!({ type: "gallery.updated", session_id: "s1", data: {} }); });
    expect(await screen.findByAltText("new.png")).toBeTruthy();
  });
});
