import { History, Loader2, Plus, Redo2, RefreshCw, Undo2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type KeyboardEvent } from "react";
import { ApiError } from "../lib/api";
import {
  conflictsOf, prefabPreviewUrl, prefabsApi, type Conflict, type GroupBy, type HistoryStep, type PrefabDetail,
  type PrefabField, type PrefabList, type PrefabSummary,
} from "../lib/prefabs";
import { actions, type Session } from "../lib/store";

/** Layout A ("Browser"): categories | prefab list | inspector. Values are read from and written to the .prefab
 *  files by backend scripts; undo and redo replay a per-project journal. No agent runs and no tokens are used. */
export function PrefabsTab({ s }: { s: Session }) {
  const sid = s.id;
  const [groupBy, setGroupBy] = useState<GroupBy>("category");
  const [list, setList] = useState<PrefabList | null>(null);
  const [group, setGroup] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [onlyEdited, setOnlyEdited] = useState(false);
  const [onlyVariants, setOnlyVariants] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<PrefabDetail | null>(null);
  const [history, setHistory] = useState<{ position: number; steps: HistoryStep[] }>({ position: 0, steps: [] });
  const [loading, setLoading] = useState(false);
  const [conflict, setConflict] = useState<{ op: "undo" | "redo"; items: Conflict[] } | null>(null);
  const [previewV, setPreviewV] = useState(0);

  const loadList = useCallback(async () => {
    setLoading(true);
    try {
      setList(await prefabsApi.list(sid, groupBy));
    } catch (e: any) {
      actions.toast(e.message, "error");
    } finally {
      setLoading(false);
    }
  }, [sid, groupBy]);
  const loadHistory = useCallback(() => prefabsApi.history(sid).then(setHistory).catch(() => {}), [sid]);
  const loadDetail = useCallback(async (path: string | null) => {
    if (!path) return setDetail(null);
    try {
      setDetail(await prefabsApi.detail(sid, path));
    } catch (e: any) {
      setDetail(null);
      actions.toast(e.message, "error");
    }
  }, [sid]);

  useEffect(() => { loadList(); loadHistory(); }, [loadList, loadHistory]);
  useEffect(() => { loadDetail(selected); }, [selected, loadDetail]);

  const refreshAfterChange = async (paths?: string[]) => {
    await Promise.all([loadList(), loadHistory()]);
    if (selected && (!paths || paths.includes(selected))) await loadDetail(selected);
    setPreviewV((v) => v + 1);
  };

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (list?.prefabs ?? []).filter((p) => (group === null || p.group === group)
      && (!onlyEdited || p.edited > 0) && (!onlyVariants || p.variant_of)
      && (!q || p.name.toLowerCase().includes(q) || p.path.toLowerCase().includes(q)
        || p.components.some((c) => c.toLowerCase().includes(q))));
  }, [list, group, query, onlyEdited, onlyVariants]);

  const undoable = history.position > 0;
  const redoable = history.position < history.steps.length;

  const step = async (op: "undo" | "redo", force = false) => {
    try {
      const r = await prefabsApi[op](sid, force);
      setConflict(null);
      await refreshAfterChange(r.paths);
    } catch (e) {
      const c = conflictsOf(e);
      if (c) setConflict({ op, items: c });
      else actions.toast((e as Error).message, "error");
    }
  };

  if (list && !list.root) {
    return <div className="p-6 text-[13px] text-muted">{list.error ?? "This session's folder isn't a Unity project."}</div>;
  }

  return (
    <div className="h-full flex flex-col min-h-0 text-[13px]">
      <div className="flex items-center gap-3 px-4 h-10 border-b border-line shrink-0">
        <span className="text-muted tabular-nums">{list ? `${list.prefabs.length} prefabs` : "Scanning…"}</span>
        <div className="flex-1" />
        <button className="btn py-0.5" onClick={() => refreshAfterChange()} disabled={loading} title="Read the .prefab files again">
          {loading ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />} Rescan
        </button>
      </div>
      <div className="flex flex-1 min-h-0">
        <Categories list={list} groupBy={groupBy} setGroupBy={(g) => { setGroupBy(g); setGroup(null); }}
          group={group} setGroup={setGroup} sid={sid} onChanged={() => refreshAfterChange()} />
        <section aria-label={`Prefabs${group ? ` in ${group}` : ""}`} className="w-[240px] xl:w-[320px] shrink-0 border-r border-line flex flex-col min-h-0">
          <div className="p-3 border-b border-line flex flex-col gap-2">
            <label className="flex flex-col gap-1 text-muted">Search
              <input type="search" className="input" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Name, component or path" />
            </label>
            <div className="flex gap-1.5 flex-wrap">
              <Chip on={onlyVariants} onClick={() => setOnlyVariants((v) => !v)}>Variants</Chip>
              <Chip on={onlyEdited} onClick={() => setOnlyEdited((v) => !v)}>Edited here</Chip>
            </div>
          </div>
          <div className="flex-1 min-h-0 overflow-y-auto p-1.5 flex flex-col gap-0.5">
            {shown.map((p) => (
              <PrefabRow key={p.path} p={p} sid={sid} v={previewV} active={p.path === selected} onClick={() => setSelected(p.path)} />
            ))}
            {list && !shown.length && <div className="p-3 text-muted">No prefabs match.</div>}
          </div>
        </section>
        <Inspector sid={sid} detail={detail} summary={list?.prefabs.find((p) => p.path === selected) ?? null} v={previewV}
          history={history} undoable={undoable} redoable={redoable} onStep={step} conflict={conflict}
          onDismissConflict={() => setConflict(null)} onOpen={(path) => setSelected(path)}
          onEdited={async (d) => { setDetail(d); await Promise.all([loadList(), loadHistory()]); setPreviewV((v) => v + 1); }} />
      </div>
    </div>
  );
}

function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button aria-pressed={on} onClick={onClick}
      className={`h-6 px-2 rounded-full border text-[12px] ${on ? "border-action text-action bg-[color-mix(in_srgb,var(--action)_10%,transparent)]" : "border-line text-muted"}`}>
      {children}
    </button>
  );
}

function Preview({ sid, path, has, size, v }: { sid: string; path: string; has: boolean; size: number; v: number }) {
  const [broken, setBroken] = useState(false);
  useEffect(() => setBroken(false), [path, v]);
  const box = { width: size, height: size };
  if (!has || broken) {
    return <span aria-hidden="true" style={box} className="shrink-0 rounded bg-sunken border border-line" />;
  }
  return <img src={prefabPreviewUrl(sid, path, v)} alt="" style={box} onError={() => setBroken(true)}
    className="shrink-0 rounded bg-[#2b2b2e] object-contain" />;
}

function PrefabRow({ p, sid, v, active, onClick }: { p: PrefabSummary; sid: string; v: number; active: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick} aria-current={active || undefined}
      className={`flex items-center gap-2.5 text-left px-2.5 py-2 rounded border ${active ? "border-action bg-[color-mix(in_srgb,var(--action)_8%,transparent)]" : "border-transparent hover:bg-sunken"}`}>
      <Preview sid={sid} path={p.path} has={p.preview} size={36} v={v} />
      <span className="flex flex-col min-w-0">
        <span className="font-medium truncate">{p.name}{p.edited > 0 && <span className="text-warn font-normal"> · {p.edited} edit{p.edited === 1 ? "" : "s"}</span>}</span>
        <span className="text-[12px] text-muted truncate">
          {p.variant_of ? `variant of ${p.variant_of.name}` : p.components.filter((c) => c !== "Transform").slice(0, 3).join(", ") || p.folder}
        </span>
      </span>
    </button>
  );
}

function Categories({ list, groupBy, setGroupBy, group, setGroup, sid, onChanged }: {
  list: PrefabList | null; groupBy: GroupBy; setGroupBy: (g: GroupBy) => void; group: string | null;
  setGroup: (g: string | null) => void; sid: string; onChanged: () => void;
}) {
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const add = async () => {
    const n = name.trim();
    if (!n) return setAdding(false);
    try {
      const { categories } = await prefabsApi.categories(sid);
      if (!categories[n]) await prefabsApi.setCategories(sid, { ...categories, [n]: [] });
      setName("");
      setAdding(false);
      onChanged();
    } catch (e: any) {
      actions.toast(e.message, "error");
    }
  };
  return (
    <section aria-label="Categories" className="w-[170px] xl:w-[220px] shrink-0 border-r border-line p-2 flex flex-col gap-0.5 overflow-y-auto">
      <label className="flex flex-col gap-1 px-1.5 pb-2 text-muted">Group by
        <select className="input" value={groupBy} onChange={(e) => setGroupBy(e.target.value as GroupBy)}>
          <option value="category">Category</option>
          <option value="folder">Folder</option>
          <option value="component">Main component</option>
        </select>
      </label>
      <GroupButton active={group === null} onClick={() => setGroup(null)} name="All prefabs" count={list?.prefabs.length ?? 0} />
      {(list?.groups ?? []).map((g) => (
        <GroupButton key={g.name} active={group === g.name} onClick={() => setGroup(g.name)} name={g.name} count={g.count} />
      ))}
      {groupBy === "category" && (adding ? (
        <input autoFocus className="input mt-2" aria-label="New category name" value={name} onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") add(); if (e.key === "Escape") setAdding(false); }} onBlur={add} />
      ) : (
        <button className="mt-2 text-left px-2 py-1.5 rounded border border-dashed border-line text-muted hover:text-[var(--text)]" onClick={() => setAdding(true)}>
          <Plus size={12} className="inline -mt-0.5" /> New category
        </button>
      ))}
    </section>
  );
}

function GroupButton({ name, count, active, onClick }: { name: string; count: number; active: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick} aria-current={active || undefined}
      className={`flex justify-between gap-2 text-left px-2 py-1.5 rounded ${active ? "bg-[color-mix(in_srgb,var(--action)_14%,transparent)] font-medium" : "hover:bg-sunken"}`}>
      <span className="truncate">{name}</span><span className="text-muted tabular-nums">{count}</span>
    </button>
  );
}

function Inspector({ sid, detail, summary, v, history, undoable, redoable, onStep, conflict, onDismissConflict, onEdited, onOpen }: {
  sid: string; detail: PrefabDetail | null; summary: PrefabSummary | null; v: number;
  history: { position: number; steps: HistoryStep[] }; undoable: boolean; redoable: boolean;
  onStep: (op: "undo" | "redo", force?: boolean) => void; conflict: { op: "undo" | "redo"; items: Conflict[] } | null;
  onDismissConflict: () => void; onEdited: (d: PrefabDetail) => void; onOpen: (path: string) => void;
}) {
  const [showHistory, setShowHistory] = useState(false);
  const next = history.steps.find((x) => !x.undone);
  return (
    <section aria-label={detail ? `Inspector: ${detail.name}` : "Inspector"} className="flex-1 min-w-0 flex flex-col min-h-0">
      <div className="px-5 py-3 border-b border-line flex items-center gap-3 flex-wrap relative">
        {detail && summary?.preview && <Preview sid={sid} path={detail.path} has size={72} v={v} />}
        <div className="flex flex-col gap-0.5 grow basis-[200px] min-w-0">
          <h2 className="m-0 text-[17px] font-semibold truncate">{detail?.name ?? "Select a prefab"}</h2>
          {detail && (
            <span className="text-muted truncate">{detail.path}{detail.variant_of && (
              <> · variant of {detail.variant_of.path
                ? <button className="text-action underline" onClick={() => onOpen(detail.variant_of!.path!)}>{detail.variant_of.name}</button>
                : detail.variant_of.name}</>)}</span>
          )}
        </div>
        <button className="btn" disabled={!undoable} onClick={() => onStep("undo")} aria-label={next ? `Undo: ${next.summary}` : "Undo"}><Undo2 size={13} /> Undo</button>
        <button className="btn" disabled={!redoable} onClick={() => onStep("redo")} aria-label="Redo"><Redo2 size={13} /> Redo</button>
        <button className="btn" aria-expanded={showHistory} onClick={() => setShowHistory((x) => !x)}><History size={13} /> History ({history.position})</button>
        {showHistory && <HistoryMenu history={history} onClose={() => setShowHistory(false)} />}
      </div>
      {conflict && (
        <div role="alert" className="mx-5 mt-3 rounded border border-warn px-3 py-2 flex flex-col gap-1.5">
          <span className="font-medium text-warn">Can't {conflict.op} cleanly: a file changed outside GDW since that step.</span>
          {conflict.items.map((c, i) => (
            <span key={i} className="text-muted">{c.path.split("/").pop()} · {c.key}: expected {c.expected}, now {c.actual}</span>
          ))}
          <span className="flex gap-2">
            <button className="btn" onClick={() => onStep(conflict.op, true)}>{conflict.op === "undo" ? "Undo" : "Redo"} anyway</button>
            <button className="btn btn-ghost" onClick={onDismissConflict}>Keep the current values</button>
          </span>
        </div>
      )}
      <div className="flex-1 min-h-0 overflow-y-auto px-5 py-4 flex flex-col gap-4">
        {!detail && <p className="m-0 text-muted">Pick a prefab to see its values. Edits are written to the .prefab file and can be undone here.</p>}
        {detail && detail.objects[0] && (
          <ObjectComponents sid={sid} detail={detail} o={detail.objects[0]} onEdited={onEdited} />
        )}
        {detail && detail.objects.length > 1 && <Children sid={sid} detail={detail} onEdited={onEdited} />}
        {detail && <p className="m-0 text-faint text-[12px]">Read from the .prefab file by a script: no agent, no tokens. Unity reimports the file when its window gets focus.</p>}
      </div>
    </section>
  );
}

const FIELD_LIMIT = 16;
const CHILD_LIMIT = 200;

/** One object's components. Long components show FIELD_LIMIT fields until expanded, so a big prefab stays fast. */
function ObjectComponents({ sid, detail, o, onEdited }: {
  sid: string; detail: PrefabDetail; o: PrefabDetail["objects"][number]; onEdited: (d: PrefabDetail) => void;
}) {
  return (
    <div className="flex flex-col gap-3">
      {o.components.map((c) => <ComponentCard key={c.file_id} sid={sid} detail={detail} c={c} onEdited={onEdited} />)}
      {!o.components.length && <div className="text-muted">No components.</div>}
    </div>
  );
}

function ComponentCard({ sid, detail, c, onEdited }: {
  sid: string; detail: PrefabDetail; c: PrefabDetail["objects"][number]["components"][number]; onEdited: (d: PrefabDetail) => void;
}) {
  const [all, setAll] = useState(false);
  const fields = all ? c.fields : c.fields.slice(0, FIELD_LIMIT);
  return (
    <div className="border border-line rounded-md">
      <div className="flex justify-between gap-2 px-3 py-2 bg-sunken border-b border-line rounded-t-md">
        <span className="font-semibold">{c.type}</span>
        <span className="text-muted truncate">{c.builtin ? "built-in" : [c.namespace, c.type].filter(Boolean).join(".")}</span>
      </div>
      {fields.length ? (
        <div className="grid gap-3 p-3" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))" }}>
          {fields.map((f) => <FieldInput key={f.key} sid={sid} path={detail.path} fileId={c.file_id} f={f}
            base={detail.variant_of?.name} onEdited={onEdited} />)}
        </div>
      ) : <div className="p-3 text-muted">No serialized values.</div>}
      {c.fields.length > FIELD_LIMIT && (
        <button className="btn btn-ghost mx-3 mb-2" onClick={() => setAll((x) => !x)}>
          {all ? "Show fewer" : `Show all ${c.fields.length} values`}
        </button>
      )}
    </div>
  );
}

/** Child objects, collapsed: open one to see its components (prefabs can have thousands of children). */
function Children({ sid, detail, onEdited }: { sid: string; detail: PrefabDetail; onEdited: (d: PrefabDetail) => void }) {
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState("");
  const children = detail.objects.slice(1);
  const q = filter.trim().toLowerCase();
  const shown = (q ? children.filter((o) => o.name.toLowerCase().includes(q) || o.components.some((c) => c.type.toLowerCase().includes(q))) : children)
    .slice(0, CHILD_LIMIT);
  const depth = useMemo(() => {
    const parent = new Map(detail.objects.map((o) => [o.file_id, o.parent_file_id]));
    const d = new Map<string, number>();
    const of = (id: string): number => {
      if (d.has(id)) return d.get(id)!;
      const p = parent.get(id);
      const v = p && parent.has(p) ? Math.min(of(p) + 1, 12) : 0;
      d.set(id, v);
      return v;
    };
    detail.objects.forEach((o) => of(o.file_id));
    return d;
  }, [detail]);
  const toggle = (id: string) => setOpen((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-3">
        <h3 className="m-0 text-[13px] font-semibold">Child objects ({children.length})</h3>
        {children.length > 12 && (
          <input type="search" className="input max-w-[240px]" aria-label="Filter child objects" placeholder="Filter by name or component"
            value={filter} onChange={(e) => setFilter(e.target.value)} />
        )}
      </div>
      {shown.map((o) => (
        <div key={o.file_id} className="flex flex-col gap-2">
          <button className="flex items-center gap-2 text-left px-2 py-1 rounded hover:bg-sunken" aria-expanded={open.has(o.file_id)}
            style={{ paddingLeft: 8 + (depth.get(o.file_id) ?? 0) * 12 }} onClick={() => toggle(o.file_id)}>
            <span aria-hidden="true" className="text-faint w-3">{open.has(o.file_id) ? "▾" : "▸"}</span>
            <span className="font-medium">{o.name}</span>
            <span className="text-muted text-[12px] truncate">{o.components.map((c) => c.type).filter((t) => t !== "Transform").join(", ")}</span>
          </button>
          {open.has(o.file_id) && <div className="pl-5"><ObjectComponents sid={sid} detail={detail} o={o} onEdited={onEdited} /></div>}
        </div>
      ))}
      {(q ? children.filter((o) => o.name.toLowerCase().includes(q)).length : children.length) > CHILD_LIMIT && (
        <span className="text-muted text-[12px] px-2">Showing the first {CHILD_LIMIT}; filter to find others.</span>
      )}
    </div>
  );
}

function HistoryMenu({ history, onClose }: { history: { position: number; steps: HistoryStep[] }; onClose: () => void }) {
  return (
    <div role="dialog" aria-label="Change history" className="absolute right-5 top-full mt-1 z-20 w-[380px] max-h-[360px] overflow-y-auto rounded-md border border-line surface-raised shadow-lg p-2 flex flex-col gap-1"
      onKeyDown={(e) => e.key === "Escape" && onClose()}>
      {!history.steps.length && <span className="p-2 text-muted">No changes yet.</span>}
      {history.steps.map((st) => (
        <div key={st.id} className={`px-2 py-1.5 rounded ${st.undone ? "text-faint" : ""}`}>
          <div className="flex justify-between gap-2">
            <span className="font-medium">{st.summary}</span>
            <span className="text-[12px] text-muted shrink-0">{st.undone ? "undone" : new Date(st.at * 1000).toLocaleTimeString()}</span>
          </div>
          <div className="text-[12px] text-muted">{st.edits.length} change{st.edits.length === 1 ? "" : "s"} · {[...new Set(st.edits.map((e) => e.path.split("/").pop()))].join(", ")}</div>
        </div>
      ))}
    </div>
  );
}

const PARTS_ORDER = ["x", "y", "z", "w", "r", "g", "b", "a"];

function FieldInput({ sid, path, fileId, f, base, onEdited }: {
  sid: string; path: string; fileId: string; f: PrefabField; base?: string; onEdited: (d: PrefabDetail) => void;
}) {
  const note = f.edited ? <span className="text-warn text-[12px]">edited · was {f.edited.was}</span>
    : f.inherited ? <span className="text-faint text-[12px]">from {base ?? "base prefab"}</span>
    : f.override ? <span className="text-muted text-[12px]">overrides {base ?? "base"}</span> : null;
  const tone = f.edited ? "border-warn bg-[color-mix(in_srgb,var(--warn)_8%,transparent)]" : f.inherited ? "border-dashed text-muted" : "";
  if (f.kind === "bool" && f.editable) {
    return (
      <label className="flex items-center gap-2 text-muted pt-5">
        <BoolInput sid={sid} path={path} fileId={fileId} f={f} onEdited={onEdited} /> {f.label} {note}
      </label>
    );
  }
  if ((f.kind === "vector" || f.kind === "color") && f.parts) {
    const keys = Object.keys(f.parts).sort((a, b) => PARTS_ORDER.indexOf(a) - PARTS_ORDER.indexOf(b));
    return (
      <fieldset className="flex flex-col gap-1 text-muted border-0 p-0 m-0 min-w-0">
        <legend className="p-0 mb-1">{f.label} {note}</legend>
        <div className="flex gap-1">
          {keys.map((k) => (
            <TextInput key={k} sid={sid} path={path} fileId={fileId} f={f} part={k} value={f.parts![k]} label={`${f.label} ${k}`}
              className={tone} onEdited={onEdited} prefix={k} />
          ))}
        </div>
      </fieldset>
    );
  }
  return (
    <label className="flex flex-col gap-1 text-muted min-w-0">
      <span>{f.label} {note}</span>
      {f.editable
        ? <TextInput sid={sid} path={path} fileId={fileId} f={f} value={f.value} label={f.label} className={tone} onEdited={onEdited} />
        : <span className="input bg-sunken text-muted truncate" title={f.value}>{f.kind === "reference" ? refLabel(f.value) : f.value || "—"}</span>}
    </label>
  );
}

const refLabel = (v: string) => (/fileID: 0\b/.test(v) ? "None" : /guid: (\w{8})/.exec(v)?.[1] ? `asset ${/guid: (\w{8})/.exec(v)![1]}…` : v);

function BoolInput({ sid, path, fileId, f, onEdited }: { sid: string; path: string; fileId: string; f: PrefabField; onEdited: (d: PrefabDetail) => void }) {
  const [busy, setBusy] = useState(false);
  const on = f.value === "1" || f.value.toLowerCase() === "true";
  return (
    <input type="checkbox" checked={on} disabled={busy} aria-label={f.label}
      onChange={async (e) => {
        setBusy(true);
        try {
          onEdited((await prefabsApi.edit(sid, { path, file_id: fileId, key: f.key, value: e.target.checked ? "1" : "0" })).detail);
        } catch (err: any) {
          actions.toast(err.message, "error");
        } finally {
          setBusy(false);
        }
      }} />
  );
}

function TextInput({ sid, path, fileId, f, part, value, label, className, onEdited, prefix }: {
  sid: string; path: string; fileId: string; f: PrefabField; part?: string; value: string; label: string;
  className: string; onEdited: (d: PrefabDetail) => void; prefix?: string;
}) {
  const [text, setText] = useState(value);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setText(value); setError(null); }, [value]);
  const commit = async () => {
    if (text === value || busy) return;
    setBusy(true);
    try {
      const r = await prefabsApi.edit(sid, { path, file_id: fileId, key: f.key, part: part ?? null, value: text });
      setError(null);
      onEdited(r.detail);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
      setText(value);
    } finally {
      setBusy(false);
    }
  };
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") (e.target as HTMLInputElement).blur();
    if (e.key === "Escape") { setText(value); setError(null); }
  };
  return (
    <span className="flex flex-col gap-0.5 min-w-0 flex-1">
      <span className="flex items-center gap-1 min-w-0">
        {prefix && <span className="text-faint text-[12px] uppercase">{prefix}</span>}
        <input className={`input ${className}`} aria-label={label} value={text} disabled={busy} aria-invalid={!!error}
          inputMode={f.kind === "string" ? "text" : "decimal"} onChange={(e) => setText(e.target.value)} onBlur={commit} onKeyDown={onKey} />
      </span>
      {error && <span role="alert" className="text-bad text-[12px]">{error}</span>}
    </span>
  );
}
