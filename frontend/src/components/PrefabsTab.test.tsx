import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { Session } from "../lib/store";

const { get, post, put, toast, ApiError } = vi.hoisted(() => {
  class ApiError extends Error {
    constructor(public status: number, message: string) { super(message); }
  }
  return { get: vi.fn(), post: vi.fn(), put: vi.fn(), toast: vi.fn(), ApiError };
});
vi.mock("../lib/api", () => ({ get, post, put, ApiError, getConn: () => ({ base: "http://x", token: "t" }) }));
vi.mock("../lib/store", () => ({ actions: { toast } }));

import { PrefabsTab } from "./PrefabsTab";
import { tabsFor } from "../lib/prefabs";

const session = { id: "s1", settings: { unity_project: true } } as unknown as Session;

const grunt = { path: "Assets/Game/Enemies/Grunt.prefab", name: "Grunt", guid: "g1", group: "Enemies", folder: "Assets/Game/Enemies",
  components: ["Transform", "Health"], variant_of: null, edited: 0, preview: false };
const brute = { ...grunt, path: "Assets/Game/Enemies/Brute.prefab", name: "Brute", guid: "g2", edited: 1,
  variant_of: { guid: "g1", name: "Grunt", path: grunt.path } };
const bullet = { ...grunt, path: "Assets/Game/Projectiles/Bullet.prefab", name: "Bullet", guid: "g3", group: "Projectiles", components: ["Transform", "Projectile"] };

const detail = (maxHealth = "80", edited: { was: string; step: number } | null = { was: "60", step: 1 }) => ({
  path: brute.path, name: "Brute", guid: "g2", variant_of: brute.variant_of, overrides: [],
  objects: [{ file_id: "100", name: "Brute", parent_file_id: null, components: [
    { file_id: "200", type: "Health", namespace: "Game", builtin: false, script_path: "Assets/Game/Health.cs", enabled: true, fields: [
      { key: "maxHealth", label: "Max Health", value: maxHealth, kind: "number", editable: true, edited, override: true },
      { key: "aggroRange", label: "Aggro Range", value: "8", kind: "number", editable: true, inherited: true },
      { key: "invulnerable", label: "Invulnerable", value: "0", kind: "bool", editable: true },
      { key: "config", label: "Config", value: "{fileID: 11400000, guid: abcdef0123456789, type: 2}", kind: "reference", editable: false },
    ] },
    { file_id: "300", type: "Transform", namespace: "", builtin: true, script_path: null, enabled: true, fields: [
      { key: "m_LocalScale", label: "Local Scale", value: "{x: 1, y: 1, z: 1}", kind: "vector", editable: true, parts: { x: "1", y: "1", z: "1" } },
    ] },
  ] }],
});

let history: any;

beforeEach(() => {
  vi.clearAllMocks();
  history = { position: 1, steps: [{ id: 1, at: 1795600000, summary: "Brute · Max Health 60 → 80", edits: [{ path: brute.path, file_id: "200", key: "maxHealth", part: null, before: "60", after: "80" }] }] };
  get.mockImplementation(async (p: string) => {
    if (p.startsWith("/sessions/s1/prefabs?")) {
      return { root: "/p", scanned_at: 1, group_by: "category", groups: [{ name: "Enemies", count: 2 }, { name: "Projectiles", count: 1 }],
        prefabs: [brute, grunt, bullet] };
    }
    if (p.startsWith("/sessions/s1/prefabs/detail")) return detail();
    if (p === "/sessions/s1/prefabs/history") return history;
    if (p === "/sessions/s1/prefabs/categories") return { categories: { Enemies: ["Assets/Game/Enemies/**"] } };
    throw new Error(`unexpected ${p}`);
  });
});
afterEach(cleanup);

async function open() {
  render(<PrefabsTab s={session} />);
  await act(async () => {});
}

it("lists prefabs by group and filters them", async () => {
  await open();
  expect(screen.getByText("3 prefabs")).toBeTruthy();
  const cats = screen.getByRole("region", { name: "Categories" });
  fireEvent.click(within(cats).getByText("Projectiles"));
  const list = screen.getByRole("region", { name: "Prefabs in Projectiles" });
  expect(within(list).getByText("Bullet")).toBeTruthy();
  expect(within(list).queryByText("Grunt")).toBeNull();
  fireEvent.click(within(cats).getByText("All prefabs"));
  fireEvent.click(screen.getByRole("button", { name: "Variants" }));
  const all = screen.getByRole("region", { name: "Prefabs" });
  expect(within(all).getByText("Brute")).toBeTruthy();
  expect(within(all).queryByText("Grunt")).toBeNull();
  expect(within(all).queryByText("Bullet")).toBeNull();
});

it("shows a prefab's values with edited, inherited and read-only fields", async () => {
  await open();
  fireEvent.click(screen.getByText("Brute"));
  await act(async () => {});
  const insp = screen.getByRole("region", { name: "Inspector: Brute" });
  expect((within(insp).getByLabelText("Max Health") as HTMLInputElement).value).toBe("80");
  expect(within(insp).getByText("edited · was 60")).toBeTruthy();
  expect(within(insp).getByText("from Grunt")).toBeTruthy();
  expect(within(insp).getByTitle(/fileID: 11400000/).textContent).toBe("asset abcdef01…");
  expect((within(insp).getByLabelText("Local Scale y") as HTMLInputElement).value).toBe("1");
});

it("writes an edit on Enter and shows a bad value inline", async () => {
  post.mockResolvedValueOnce({ ok: true, step: 2, detail: detail("95", { was: "60", step: 2 }) });
  await open();
  fireEvent.click(screen.getByText("Brute"));
  await act(async () => {});
  const input = screen.getByLabelText("Max Health") as HTMLInputElement;
  fireEvent.change(input, { target: { value: "95" } });
  await act(async () => { fireEvent.blur(input); });
  expect(post).toHaveBeenCalledWith("/sessions/s1/prefabs/edit", { path: brute.path, file_id: "200", key: "maxHealth", part: null, value: "95" });
  expect((screen.getByLabelText("Max Health") as HTMLInputElement).value).toBe("95");

  post.mockRejectedValueOnce(new ApiError(400, "maxHealth needs a number"));
  const again = screen.getByLabelText("Max Health") as HTMLInputElement;
  fireEvent.change(again, { target: { value: "lots" } });
  await act(async () => { fireEvent.blur(again); });
  expect(screen.getByRole("alert").textContent).toBe("maxHealth needs a number");
  expect((screen.getByLabelText("Max Health") as HTMLInputElement).value).toBe("95");

  post.mockResolvedValueOnce({ ok: true, step: 3, detail: detail() });
  await act(async () => { fireEvent.click(screen.getByLabelText("Local Scale x")); });
  const sx = screen.getByLabelText("Local Scale x") as HTMLInputElement;
  fireEvent.change(sx, { target: { value: "1.5" } });
  await act(async () => { fireEvent.blur(sx); });
  expect(post).toHaveBeenLastCalledWith("/sessions/s1/prefabs/edit", { path: brute.path, file_id: "300", key: "m_LocalScale", part: "x", value: "1.5" });
});

it("undoes, and offers to force it when the file changed since", async () => {
  post.mockResolvedValueOnce({ ok: true, position: 0, paths: [brute.path] });
  await open();
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Undo: Brute · Max Health 60 → 80" })); });
  expect(post).toHaveBeenCalledWith("/sessions/s1/prefabs/undo", { force: false });

  post.mockRejectedValueOnce(new ApiError(409, JSON.stringify({ conflict: [{ path: brute.path, key: "maxHealth", expected: "80", actual: "90" }] })));
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: /^Undo/ })); });
  const alert = screen.getByRole("alert");
  expect(alert.textContent).toContain("expected 80, now 90");
  post.mockResolvedValueOnce({ ok: true, position: 0, paths: [brute.path] });
  await act(async () => { fireEvent.click(within(alert).getByRole("button", { name: "Undo anyway" })); });
  expect(post).toHaveBeenLastCalledWith("/sessions/s1/prefabs/undo", { force: true });
  expect(screen.queryByRole("alert")).toBeNull();
});

it("says so when the session isn't in a Unity project, and hides the tab when known", async () => {
  get.mockImplementation(async (p: string) => (p.startsWith("/sessions/s1/prefabs?")
    ? { root: null, error: "no Unity project in this session's folder", prefabs: [], groups: [] }
    : { position: 0, steps: [] }));
  await open();
  expect(screen.getByText("no Unity project in this session's folder")).toBeTruthy();
  expect(tabsFor(false)).not.toContain("prefabs");
  expect(tabsFor(true)).toContain("prefabs");
  expect(tabsFor(undefined)).toContain("prefabs");
});

it("keeps big prefabs fast: children collapsed, long components capped until expanded", async () => {
  const many = Array.from({ length: 20 }, (_, i) => ({ key: `f${i}`, label: `Field ${i}`, value: String(i), kind: "number", editable: true }));
  const big = {
    ...detail(), objects: [
      { file_id: "1", name: "Root", parent_file_id: null, components: [
        { file_id: "11", type: "Spawner", namespace: "", builtin: false, script_path: null, enabled: true, fields: many }] },
      { file_id: "2", name: "Muzzle", parent_file_id: "1", components: [
        { file_id: "21", type: "Light2D", namespace: "", builtin: false, script_path: null, enabled: true,
          fields: [{ key: "intensity", label: "Intensity", value: "2", kind: "number", editable: true }] }] },
    ],
  };
  get.mockImplementation(async (p: string) => (p.startsWith("/sessions/s1/prefabs/detail") ? big
    : p.startsWith("/sessions/s1/prefabs?") ? { root: "/p", scanned_at: 1, group_by: "category", groups: [], prefabs: [brute] }
    : history));
  await open();
  fireEvent.click(screen.getByText("Brute"));
  await act(async () => {});
  expect(screen.queryByLabelText("Field 17")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Show all 20 values" }));
  expect(screen.getByLabelText("Field 17")).toBeTruthy();
  expect(screen.queryByLabelText("Intensity")).toBeNull();
  const child = screen.getByRole("button", { name: /Muzzle/ });
  expect(child.getAttribute("aria-expanded")).toBe("false");
  fireEvent.click(child);
  expect(screen.getByLabelText("Intensity")).toBeTruthy();
});
