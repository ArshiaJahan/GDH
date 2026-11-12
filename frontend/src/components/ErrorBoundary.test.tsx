import { cleanup, render, screen } from "@testing-library/react";
import { lazy, Suspense } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ErrorBoundary, installPreloadReload } from "./ErrorBoundary";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("ErrorBoundary", () => {
  it("shows the error with Reload instead of a blank app when a lazy page's chunk fails", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const Broken = lazy(() => Promise.reject(new Error("Failed to fetch dynamically imported module: /assets/Settings-abc.js")));
    render(<ErrorBoundary resetKey="settings"><Suspense fallback="Loading…"><Broken /></Suspense></ErrorBoundary>);
    expect(await screen.findByText("Something went wrong loading this page")).toBeTruthy();
    expect(screen.getByText(/Settings-abc\.js/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Reload" })).toBeTruthy();
  });

  it("clears when the page changes", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const Boom = () => { throw new Error("boom"); };
    const { rerender } = render(<ErrorBoundary resetKey="a"><Boom /></ErrorBoundary>);
    expect(screen.getByText("boom")).toBeTruthy();
    rerender(<ErrorBoundary resetKey="b"><p>fine</p></ErrorBoundary>);
    expect(screen.getByText("fine")).toBeTruthy();
  });
});

describe("installPreloadReload", () => {
  it("reloads once on vite:preloadError, not in a loop", () => {
    const target = new EventTarget();
    const store: Record<string, string> = {};
    const reload = vi.fn();
    const win = Object.assign(target, {
      sessionStorage: { getItem: (k: string) => store[k] ?? null, setItem: (k: string, v: string) => { store[k] = v; } },
      location: { reload },
    }) as unknown as Window;
    let t = 1_000_000;
    installPreloadReload(win, () => t);
    const fire = () => { const e = new Event("vite:preloadError", { cancelable: true }); win.dispatchEvent(e); return e; };
    expect(fire().defaultPrevented).toBe(true);
    expect(reload).toHaveBeenCalledTimes(1);
    t += 5_000; // the reloaded page fails again right away: no second reload, the boundary shows it
    expect(fire().defaultPrevented).toBe(false);
    expect(reload).toHaveBeenCalledTimes(1);
    t += 120_000; // a later update may reload again
    fire();
    expect(reload).toHaveBeenCalledTimes(2);
  });
});
