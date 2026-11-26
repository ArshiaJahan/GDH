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
import { tabsFor, type PrefabDetail } from "../lib/prefabs";

const session = { id: "s1", settings: { unity_project: true } } as unknown as Session;

const grunt = { path: "Assets/Game/Enemies/Grunt.prefab", name: "Grunt", guid: "g1", group: "Enemies", folder: "Assets/Game/Enemies",
  components: ["Transform", "Health"], variant_of: null, edited: 0, preview: false };
const brute = { ...grunt, path: "Assets/Game/Enemies/Brute.prefab", name: "Brute", guid: "g2", edited: 1,
  variant_of: { guid: "g1", name: "Grunt", path: grunt.path } };
const bullet = { ...grunt, path: "Assets/Game/Projectiles/Bullet.prefab", name: "Bullet", guid: "g3", group: "Projectiles", components: ["Transform", "Projectile"] };

const detail = (maxHealth = "80", edited: { was: string; step: number } | null = { was: "60", step: 1 }): PrefabDetail => ({
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

const gruntDetail = (maxHealth = "60") => {
  const d = detail(maxHealth, null);
  const [root] = d.objects;
  return { ...d, ...grunt, objects: [{ ...root, file_id: "101", name: grunt.name,
    components: root.components.map((c, i) => ({ ...c, file_id: String(201 + 100 * i) })) }] };
};

let history: any;

beforeEach(() => {
  vi.clearAllMocks();
  history = { position: 1, steps: [{ id: 1, at: 1795600000, summary: "Brute · Max Health 60 → 80", edits: [{ path: brute.path, file_id: "200", key: "maxHealth", part: null, before: "60", after: "80" }] }] };
  get.mockImplementation(async (p: string) => {
    if (p.startsWith("/sessions/s1/prefabs?")) {
      return { root: "/p", scanned_at: 1, group_by: "category", groups: [{ name: "Enemies", count: 2 }, { name: "Projectiles", count: 1 }],
        prefabs: [brute, grunt, bullet] };
    }
    if (p.startsWith("/sessions/s1/prefabs/detail")) return p.endsWith(encodeURIComponent(grunt.path)) ? gruntDetail() : detail();
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

async function selectPair() {
  const list = within(screen.getByRole("region", { name: "Prefabs" }));
  await act(async () => {
    fireEvent.click(list.getByText("Brute"), { metaKey: true });
    fireEvent.click(list.getByText("Grunt"), { metaKey: true });
  });
  return within(screen.getByRole("region", { name: "Bulk edit" }));
}

it("shows common editable values and mixed values for two Cmd-selected prefabs", async () => {
  await open();
  const bulk = await selectPair();
  expect(bulk.getByRole("heading", { name: "Bulk edit · 2 prefabs" })).toBeTruthy();
  expect(bulk.getByText("6 fields in common")).toBeTruthy();
  expect((bulk.getByLabelText("Aggro Range") as HTMLInputElement).value).toBe("8");
  expect((bulk.getByLabelText("Local Scale x") as HTMLInputElement).value).toBe("1");
  const mixed = bulk.getByPlaceholderText("mixed") as HTMLInputElement;
  expect(mixed).toBe(bulk.getByLabelText("Max Health"));
  expect(mixed.value).toBe("");
  expect(bulk.queryByText("Config")).toBeNull();
  await act(async () => { fireEvent.blur(mixed); });
  expect(post).not.toHaveBeenCalled();
});

it.each([
  { value: "95", targets: [[brute.path, "200"], [grunt.path, "201"]] },
  { value: "80", targets: [[grunt.path, "201"]] },
])("batches a bulk value of $value, skipping prefabs already at that value", async ({ value, targets }) => {
  await open();
  const bulk = await selectPair();
  const mockGet = get.getMockImplementation()!;
  post.mockImplementationOnce(async () => {
    get.mockImplementation(async (p: string) => !p.startsWith("/sessions/s1/prefabs/detail") ? mockGet(p)
      : p.endsWith(encodeURIComponent(grunt.path)) ? gruntDetail(value) : detail(value));
    return { ok: true, step: 2 };
  });
  get.mockClear();
  const input = bulk.getByLabelText("Max Health") as HTMLInputElement;
  input.focus();
  fireEvent.change(input, { target: { value } });
  await act(async () => { fireEvent.keyDown(input, { key: "Enter" }); });
  expect(post).toHaveBeenCalledTimes(1);
  expect(post).toHaveBeenCalledWith("/sessions/s1/prefabs/edit_many", {
    edits: targets.map(([path, file_id]) => ({ path, file_id, key: "maxHealth", part: null, value })),
    summary: `${targets.length} prefabs · Max Health → ${value}`,
  });
  expect(get).toHaveBeenCalledWith("/sessions/s1/prefabs?group_by=category");
  expect(get).toHaveBeenCalledWith("/sessions/s1/prefabs/history");
  for (const p of [brute, grunt]) expect(get).toHaveBeenCalledWith(`/sessions/s1/prefabs/detail?path=${encodeURIComponent(p.path)}`);
  expect((bulk.getByLabelText("Max Health") as HTMLInputElement).value).toBe(value);
  expect(toast).toHaveBeenCalledWith(`Set Max Health on ${targets.length} prefabs`);
  await act(async () => { fireEvent.blur(bulk.getByLabelText("Max Health")); });
  expect(post).toHaveBeenCalledTimes(1);
});

it("shows a rejected bulk value inline and restores the mixed input", async () => {
  await open();
  const bulk = await selectPair();
  post.mockRejectedValueOnce(new ApiError(400, "Expected a finite number"));
  const input = bulk.getByLabelText("Max Health") as HTMLInputElement;
  fireEvent.change(input, { target: { value: "lots" } });
  await act(async () => { fireEvent.blur(input); });
  expect(within(input.closest("label")!).getByRole("alert").textContent).toBe("Expected a finite number");
  expect(input.value).toBe("");
  expect(input.placeholder).toBe("mixed");
});

it("matches child paths, same-type component indices, and individual vector parts", async () => {
  const withChildren = (d: PrefabDetail, variant: boolean): PrefabDetail => {
    const [root] = d.objects;
    const transform = root.components[1];
    const scale = transform.fields[0];
    const baseId = variant ? 400 : 500;
    return { ...d, objects: [{ ...root, components: [] },
      { file_id: String(baseId), name: "Mount", parent_file_id: root.file_id, components: [] },
      { file_id: String(baseId + 1), name: "Muzzle", parent_file_id: String(baseId), components: [
        { ...transform, file_id: String(baseId + 2), fields: [{ ...scale, parts: variant ? { x: "1", y: "1" } : { x: "1", z: "1" } }] },
        { ...transform, file_id: String(baseId + 3), fields: [{ ...scale, parts: { x: variant ? "2" : "3" } }] },
      ] },
      { file_id: String(baseId + 4), name: variant ? "Other" : "Muzzle", parent_file_id: root.file_id, components: [transform] },
    ] };
  };
  const mockGet = get.getMockImplementation()!;
  get.mockImplementation(async (p: string) => !p.startsWith("/sessions/s1/prefabs/detail") ? mockGet(p)
    : p.endsWith(encodeURIComponent(grunt.path)) ? withChildren(gruntDetail(), false) : withChildren(detail(), true));
  await open();
  const bulk = await selectPair();
  expect(bulk.getByText("2 fields in common")).toBeTruthy();
  expect(bulk.getAllByRole("heading", { name: "Mount/Muzzle" })).toHaveLength(2);
  const [first, second] = bulk.getAllByLabelText<HTMLInputElement>("Local Scale x");
  expect(first.value).toBe("1");
  expect(second.placeholder).toBe("mixed");
  post.mockResolvedValueOnce({ ok: true, step: 2 });
  fireEvent.change(second, { target: { value: "4" } });
  await act(async () => { fireEvent.blur(second); });
  expect(post).toHaveBeenCalledWith("/sessions/s1/prefabs/edit_many", {
    edits: [[brute.path, "403"], [grunt.path, "503"]].map(([path, file_id]) => ({ path, file_id, key: "m_LocalScale", part: "x", value: "4" })),
    summary: "2 prefabs · Local Scale x → 4",
  });
});

it("Shift-selects a range of shown rows and clears it on Escape or plain click", async () => {
  await open();
  const list = within(screen.getByRole("region", { name: "Prefabs" }));
  await act(async () => {
    fireEvent.click(list.getByText("Brute"));
    fireEvent.click(list.getByText("Bullet"), { shiftKey: true });
  });
  expect(screen.getByRole("heading", { name: "Bulk edit · 3 prefabs" })).toBeTruthy();
  expect(list.getAllByRole("checkbox", { checked: true })).toHaveLength(3);
  await act(async () => { fireEvent.keyDown(list.getByText("Bullet"), { key: "Escape" }); });
  expect(screen.queryByRole("region", { name: "Bulk edit" })).toBeNull();
  expect(list.queryAllByRole("checkbox", { checked: true })).toHaveLength(0);

  await act(async () => {
    fireEvent.change(list.getByRole("searchbox"), { target: { value: "Health" } });
    fireEvent.click(list.getByRole("checkbox", { name: "Select Brute" }));
    fireEvent.click(list.getByText("Grunt"), { shiftKey: true });
  });
  expect(screen.getByRole("heading", { name: "Bulk edit · 2 prefabs" })).toBeTruthy();
  await act(async () => { fireEvent.click(list.getByText("Grunt")); });
  expect(screen.getByRole("region", { name: "Inspector: Grunt" })).toBeTruthy();
  expect(list.queryAllByRole("checkbox", { checked: true })).toHaveLength(0);
});

it("does not fetch bulk details for more than 50 selected prefabs", async () => {
  const mockGet = get.getMockImplementation()!;
  const prefabs = Array.from({ length: 51 }, (_, i) => ({ ...grunt, name: `Prefab ${i}`, path: `${i}.prefab` }));
  get.mockImplementation(async (p: string) => p.startsWith("/sessions/s1/prefabs?")
    ? { root: "/p", scanned_at: 1, group_by: "category", groups: [], prefabs } : mockGet(p));
  await open();
  await act(async () => { fireEvent.click(screen.getByRole("checkbox", { name: "Select Prefab 0" })); });
  get.mockClear();
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Select all shown" })); });
  const bulk = within(screen.getByRole("region", { name: "Bulk edit" }));
  expect(bulk.getByRole("heading", { name: "Bulk edit · 51 prefabs" })).toBeTruthy();
  expect(bulk.getByText("Select 50 or fewer to bulk edit")).toBeTruthy();
  expect(get).not.toHaveBeenCalled();
});

it("loads bulk detail at most six requests at a time", async () => {
  const mockGet = get.getMockImplementation()!;
  const prefabs = Array.from({ length: 8 }, (_, i) => ({ ...grunt, name: `Prefab ${i}`, path: `${i}.prefab` }));
  const pending: (() => void)[] = [];
  get.mockImplementation(async (p: string) => {
    if (p.startsWith("/sessions/s1/prefabs?")) return { root: "/p", scanned_at: 1, group_by: "category", groups: [], prefabs };
    if (p.startsWith("/sessions/s1/prefabs/detail")) return new Promise((resolve) => {
      pending.push(() => resolve({ ...detail(), path: p.split("=")[1] }));
    });
    return mockGet(p);
  });
  await open();
  await act(async () => {
    fireEvent.click(screen.getByText("Prefab 0"));
    fireEvent.click(screen.getByText("Prefab 7"), { shiftKey: true });
  });
  expect(screen.getByRole("status").textContent).toContain("Loading prefab details");
  expect(pending).toHaveLength(6);
  await act(async () => { pending.splice(0, 2).forEach((resolve) => resolve()); });
  expect(pending).toHaveLength(6);
  await act(async () => { pending.splice(0).forEach((resolve) => resolve()); });
  expect(screen.getByText("6 fields in common")).toBeTruthy();
});

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

it("renders previews with Unity in the background and refreshes thumbnails when done", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  try {
    let status: any = { running: false, result: null };
    const base = get.getMockImplementation()!;
    get.mockImplementation(async (p: string) => (p === "/sessions/s1/prefabs/previews/status" ? status : base(p)));
    post.mockResolvedValueOnce({ running: true, result: null });
    await open();
    status = { running: true, result: null };
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /Render previews/ })); });
    expect(post).toHaveBeenCalledWith("/sessions/s1/prefabs/previews", { force: false });
    expect(screen.getByRole("button", { name: /Rendering/ })).toHaveProperty("disabled", true);
    status = { running: true, waiting_approval: true, result: null };
    await act(async () => { await vi.advanceTimersByTimeAsync(1600); });
    expect(screen.getByRole("status").textContent).toContain("Approve the Unity card in the Chat tab");
    const scans = get.mock.calls.filter(([p]) => p.startsWith("/sessions/s1/prefabs?")).length;
    status = { running: false, result: { status: "pass", summary: "3 previews rendered, 0 unchanged", counts: { rendered: 3 }, actions: [] } };
    await act(async () => { await vi.advanceTimersByTimeAsync(1600); });
    expect(toast).toHaveBeenCalledWith("3 previews rendered, 0 unchanged", "info");
    expect(get.mock.calls.filter(([p]) => p.startsWith("/sessions/s1/prefabs?")).length).toBe(scans + 1);
    expect(screen.getByRole("button", { name: /Render previews/ })).toHaveProperty("disabled", false);

    post.mockResolvedValueOnce({ running: true, result: null });
    status = { running: true, result: null };
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /Render previews/ }), { altKey: true }); });
    expect(post).toHaveBeenLastCalledWith("/sessions/s1/prefabs/previews", { force: true });
    status = { running: false, result: { status: "skipped", summary: "needs_harness: …", counts: {}, actions: ["install_harness"] } };
    await act(async () => { await vi.advanceTimersByTimeAsync(1600); });
    expect(toast).toHaveBeenLastCalledWith(expect.stringContaining("install them from the Unity status chip"), "error");
  } finally {
    vi.useRealTimers();
  }
});
