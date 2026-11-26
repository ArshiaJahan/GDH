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
  file_id: string; type: string; namespace: string; builtin: boolean; script_path: string | null; package?: string | null;
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

export type PrefabEdit = { path: string; file_id: string; key: string; part?: string | null; value: string };

const base = (sid: string) => `/sessions/${encodeURIComponent(sid)}/prefabs`;

export const prefabsApi = {
  list: (sid: string, groupBy: GroupBy) => get<PrefabList>(`${base(sid)}?group_by=${groupBy}`),
  detail: (sid: string, path: string) => get<PrefabDetail>(`${base(sid)}/detail?path=${encodeURIComponent(path)}`),
  edit: (sid: string, e: PrefabEdit) =>
    post<{ ok: boolean; step: number; detail: PrefabDetail }>(`${base(sid)}/edit`, e),
  editMany: (sid: string, edits: PrefabEdit[], summary?: string) =>
    post<{ ok: boolean; step: number }>(`${base(sid)}/edit_many`, { edits, summary }),
  undo: (sid: string, force = false) => post<{ ok: boolean; position: number; paths: string[] }>(`${base(sid)}/undo`, { force }),
  redo: (sid: string, force = false) => post<{ ok: boolean; position: number; paths: string[] }>(`${base(sid)}/redo`, { force }),
  history: (sid: string) => get<{ position: number; steps: HistoryStep[] }>(`${base(sid)}/history`),
  setCategories: (sid: string, categories: Record<string, string[]>) =>
    put<{ categories: Record<string, string[]> }>(`${base(sid)}/categories`, { categories }),
  categories: (sid: string) => get<{ categories: Record<string, string[]> }>(`${base(sid)}/categories`),
  renderPreviews: (sid: string, force = false) => post<PreviewJob>(`${base(sid)}/previews`, { force }),
  previewsStatus: (sid: string) => get<PreviewJob>(`${base(sid)}/previews/status`),
};

/** A Unity render of prefab thumbnails (runs in the background after an approval card). */
export type PreviewJob = {
  running: boolean; started_at?: number; finished_at?: number | null; waiting_approval?: boolean;
  result: null | { status: string; summary: string; route?: string; counts: Record<string, number>; actions: string[]; menu?: string | null };
};

export const prefabBool = (value: string) => value === "1" || value.toLowerCase() === "true";

type EditableSlot = { component: PrefabComponent; group: string; objectPath: string; field: PrefabField; edit: PrefabEdit };

function editableSlots(detail: PrefabDetail) {
  const slots = new Map<string, EditableSlot | null>();
  const paths = new Map<string, string[]>();
  // Detail lists parents before children. Omit each root name from its relative paths.
  for (const object of detail.objects) {
    const path = object.parent_file_id ? [...(paths.get(object.parent_file_id) ?? []), object.name] : [];
    paths.set(object.file_id, path);
    const indices = new Map<string, number>();
    for (const component of object.components) {
      const index = indices.get(component.type) ?? 0;
      indices.set(component.type, index + 1);
      const group = JSON.stringify([path, component.type, index]);
      for (const field of component.fields) {
        if (!field.editable) continue;
        const parts = field.parts ? Object.entries(field.parts) : [[null, field.value]] as const;
        for (const [part, value] of parts) {
          const key = JSON.stringify([group, field.key, part]);
          const edit = { path: detail.path, file_id: component.file_id, key: field.key, part,
            value: field.kind === "bool" ? (prefabBool(value) ? "1" : "0") : value };
          // Duplicate child names can leave the same path ambiguous.
          slots.set(key, slots.has(key) ? null : { component, group, objectPath: path.join("/"), field, edit });
        }
      }
    }
  }
  return slots;
}

type CommonSlot = { key: string; label: string; kind: FieldKind; value: string | null; edits: PrefabEdit[] };
type CommonComponent = Pick<EditableSlot, "component" | "objectPath"> & { slots: CommonSlot[] };

export function commonPrefabFields(details: PrefabDetail[]) {
  const [first, ...rest] = details.map(editableSlots);
  const groups = new Map<string, CommonComponent>();
  for (const [key, slot] of first ?? []) {
    if (!slot) continue;
    const matches = rest.map((slots) => slots.get(key));
    if (!matches.every((match) => match != null)) continue;
    const { component, group, objectPath, field, edit } = slot;
    const edits = [edit, ...matches.map((match) => match.edit)];
    const label = edit.part === null ? field.label : `${field.label} ${edit.part}`;
    const value = edits.every((target) => target.value === edit.value) ? edit.value : null;
    if (!groups.has(group)) groups.set(group, { component, objectPath, slots: [] });
    groups.get(group)!.slots.push({ key, label, kind: field.kind, value, edits });
  }
  return groups;
}

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
