import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { Session } from "../../lib/store";

const { get, patch } = vi.hoisted(() => ({
  get: vi.fn(async (p: string) => p === "/skills" ? { skills: ["delegation", "play-verify", "perf-pass", "graphify"].map((name) => ({ name, description: name })) } : []),
  patch: vi.fn(),
}));
vi.mock("../../lib/api", () => ({ get, patch, post: vi.fn() }));
vi.mock("../../lib/store", () => ({ actions: { go: vi.fn(), toast: vi.fn() } }));
vi.mock("../SidePanel", () => ({ Card: ({ children }: { children: ReactNode }) => <div>{children}</div> }));

import { ConnectorsCard } from "./ConnectorsCard";

beforeEach(() => vi.clearAllMocks());
afterEach(cleanup);

const session = (progressive = true, status = "idle"): Session => ({
  id: "s1", title: "Skills", status, created_at: 0, updated_at: 0, pinned: false, folder: null,
  model: "claude-opus-5-5", effort: "medium", account: "default", mode: "ask", harness: "builtin", location: "local",
  group_id: null, sort_order: 0, archived: false, archived_at: null, deleted: false, deleted_at: null,
  activity_at: null, last_read_at: null, unread: false, last_error: null, forked_from: null,
  settings: {
    skills: ["delegation", "perf-pass", "play-verify"],
    ...(progressive ? { skill_mode: "progressive", pinned_skills: ["delegation"], loaded_skills: ["perf-pass", "play-verify"] } : {}),
  },
});

it("shows pins, LRU order and index count; unload changes only loaded_skills", async () => {
  render(<ConnectorsCard s={session()} />);
  await act(async () => {});
  expect(screen.getByText("Pinned")).toBeTruthy();
  expect(screen.getByText("Loaded")).toBeTruthy();
  expect(screen.getByText("Index: 3 skills")).toBeTruthy();
  const unloads = screen.getAllByRole("button", { name: /^Unload / });
  expect(unloads.map((b) => b.getAttribute("aria-label"))).toEqual(["Unload perf-pass", "Unload play-verify"]);
  fireEvent.click(unloads[0]);
  expect(patch).toHaveBeenCalledWith("/sessions/s1", { settings: { loaded_skills: ["play-verify"] } });
});

it("can pin a loaded skill and unpin other pins while delegation stays pinned", async () => {
  const s = session();
  s.settings.pinned_skills.push("graphify");
  render(<ConnectorsCard s={s} />);
  await act(async () => {});
  fireEvent.click(screen.getByRole("button", { name: "Pin play-verify" }));
  expect(patch).toHaveBeenLastCalledWith("/sessions/s1", { settings: {
    pinned_skills: ["delegation", "graphify", "play-verify"], loaded_skills: ["perf-pass"],
    skills: ["delegation", "perf-pass", "play-verify"],
  } });
  fireEvent.click(screen.getByRole("button", { name: "Unpin graphify" }));
  expect(patch).toHaveBeenLastCalledWith("/sessions/s1", { settings: { pinned_skills: ["delegation"] } });
  expect((screen.getByRole("button", { name: "Unpin delegation" }) as HTMLButtonElement).disabled).toBe(true);
});

it("keeps pin changes disabled during a turn and still allows unloading", async () => {
  render(<ConnectorsCard s={session(true, "running")} />);
  await act(async () => {});
  for (const name of ["Pin skill…", "Pin play-verify", "Unpin delegation"]) {
    expect((screen.getByRole("button", { name }) as HTMLButtonElement).disabled).toBe(true);
  }
  expect((screen.getByRole("button", { name: "Unload play-verify" }) as HTMLButtonElement).disabled).toBe(false);
});

it("retains the enabled-skill controls for legacy sessions", async () => {
  render(<ConnectorsCard s={session(false)} />);
  await act(async () => {});
  expect(screen.queryByText("Pinned")).toBeNull();
  expect(screen.getByRole("button", { name: "Add skill…" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Remove play-verify" }));
  expect(patch).toHaveBeenCalledWith("/sessions/s1", { settings: { skills: ["delegation", "perf-pass"] } });
});
