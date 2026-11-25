import { ApiError, get, getConn, post, put } from "./api";
import type { SessionTab } from "./store";

/** Prefabs tab API (backend features/prefabs.py). Everything here is read and written by scripts: no agent, no tokens. */

export type GroupBy = "category" | "folder" | "component";

export type PrefabRef = { guid: string; name: string; path: string | null };

export type PrefabSummary = {
  path: string; name: string; guid: string; group: string; folder: string;
  components: string[]; variant_of: PrefabRef | null; edited: number; preview: boolean;
};

export type PrefabList = {
  root: string | null; error?: string; scanned_at: number; group_by: GroupBy;
  groups: { name: string; count: number }[]; prefabs: PrefabSummary[];
};

export type FieldKind = "number" | "bool" | "string" | "vector" | "color" | "reference" | "list" | "other";

export type PrefabField = {
  key: string; label: string; value: string; kind: FieldKind; editable: boolean;
  parts?: Record<string, string> | null; edited?: { was: string; step: number } | null;
  inherited?: boolean; override?: boolean;
};

export type PrefabComponent = {
  file_id: string; type: string; namespace: string; builtin: boolean; script_path: string | null;
  enabled: boolean; fields: PrefabField[];
};

export type PrefabObject = { file_id: string; name: string; parent_file_id: string | null; components: PrefabComponent[] };

export type PrefabDetail = {
  path: string; name: string; guid: string; variant_of: PrefabRef | null; objects: PrefabObject[];
  overrides: { target_file_id: string; target_guid: string; property_path: string; value: string }[];
};

export type HistoryStep = {
  id: number; at: number; summary: string; undone?: boolean;
  edits: { path: string; file_id: string; key: string; part: string | null; before: string; after: string }[];
};

export type Conflict = { path: string; key: string; expected: string; actual: string };

const base = (sid: string) => `/sessions/${encodeURIComponent(sid)}/prefabs`;

export const prefabsApi = {
  list: (sid: string, groupBy: GroupBy) => get<PrefabList>(`${base(sid)}?group_by=${groupBy}`),
  detail: (sid: string, path: string) => get<PrefabDetail>(`${base(sid)}/detail?path=${encodeURIComponent(path)}`),
  edit: (sid: string, e: { path: string; file_id: string; key: string; part?: string | null; value: string }) =>
    post<{ ok: boolean; step: number; detail: PrefabDetail }>(`${base(sid)}/edit`, e),
  undo: (sid: string, force = false) => post<{ ok: boolean; position: number; paths: string[] }>(`${base(sid)}/undo`, { force }),
  redo: (sid: string, force = false) => post<{ ok: boolean; position: number; paths: string[] }>(`${base(sid)}/redo`, { force }),
  history: (sid: string) => get<{ position: number; steps: HistoryStep[] }>(`${base(sid)}/history`),
  setCategories: (sid: string, categories: Record<string, string[]>) =>
    put<{ categories: Record<string, string[]> }>(`${base(sid)}/categories`, { categories }),
  categories: (sid: string) => get<{ categories: Record<string, string[]> }>(`${base(sid)}/categories`),
};

/** An <img> URL for a prefab's cached preview (the token goes in the query, as for /api/file). */
export function prefabPreviewUrl(sid: string, path: string, version = 0): string {
  const { base: b, token } = getConn();
  const q = new URLSearchParams({ path, token, v: String(version) });
  return `${b}/api${base(sid)}/preview?${q}`;
}

/** The conflicts in a 409 from undo/redo, or null for any other error. */
export function conflictsOf(e: unknown): Conflict[] | null {
  if (!(e instanceof ApiError) || e.status !== 409) return null;
  try {
    const d = JSON.parse(e.message);
    return Array.isArray(d?.conflict) ? d.conflict : null;
  } catch {
    return null;
  }
}

const ALL_TABS: SessionTab[] = ["chat", "subagents", "gallery", "prefabs"];

/** Session tabs: Prefabs only for sessions that may be in a Unity project (settings.unity_project is frozen at
 *  session start; unknown still shows it). */
export const tabsFor = (unityProject: unknown): SessionTab[] => ALL_TABS.filter((t) => t !== "prefabs" || unityProject !== false);
