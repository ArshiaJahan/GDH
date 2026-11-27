import { History, Image as ImageIcon, Loader2, Plus, Redo2, RefreshCw, Undo2 } from "lucide-react";
import { Fragment, useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent } from "react";
import { ApiError } from "../lib/api";
import {
  commonPrefabFields, conflictsOf, prefabBool, prefabPreviewUrl, prefabsApi, type Conflict, type GroupBy, type HistoryStep, type PrefabDetail,
  type PrefabField, type PrefabList, type PrefabSummary, type PreviewJob,
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
  const [multi, setMulti] = useState(new Set<string>());
  const anchor = useRef<string | null>(null);
  const bulkPaths = useMemo(() => [...multi], [multi]);
  const singlePath = bulkPaths.length >= 2 ? null : bulkPaths[0] ?? selected;
  const [detail, setDetail] = useState<PrefabDetail | null>(null);
  const [detailV, setDetailV] = useState(0);
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
  useEffect(() => { loadList(); loadHistory(); }, [loadList, loadHistory]);
  useEffect(() => {
    if (!singlePath) return setDetail(null);
    let active = true;
    prefabsApi.detail(sid, singlePath).then((d) => {
      if (active) setDetail(d);
    }).catch((e) => {
      if (!active) return;
      setDetail(null);
      actions.toast(e.message, "error");
    });
    return () => { active = false; };
  }, [sid, singlePath, detailV]);

  const clearMulti = useCallback(() => {
    setMulti((current) => current.size ? new Set() : current);
    anchor.current = null;
  }, []);
  useEffect(() => {
    const escape = (e: globalThis.KeyboardEvent) => { if (e.key === "Escape") clearMulti(); };
    window.addEventListener("keydown", escape);
    return () => window.removeEventListener("keydown", escape);
  }, [clearMulti]);

  const refreshAfterChange = async () => {
    await Promise.all([loadList(), loadHistory()]);
    setDetailV((v) => v + 1);
    setPreviewV((v) => v + 1);
  };

  const [rendering, setRendering] = useState(false);
  const [awaitingApproval, setAwaitingApproval] = useState(false);
  const finishRender = useCallback(async (job: PreviewJob) => {
    setRendering(job.running);
    setAwaitingApproval(Boolean(job.running && job.waiting_approval));
    if (job.running || !job.result) return;
    const r = job.result;
    const ok = r.status === "pass";
    actions.toast(ok ? r.summary : r.actions.includes("install_harness")
      ? "Prefab previews need the headless harness scripts: install them from the Unity status chip, then try again."
      : r.summary, ok ? "info" : "error");
    if (ok) {
      await loadList();
      setPreviewV((v) => v + 1);
    }
  }, [loadList]);
  useEffect(() => {
    if (!rendering) return;
    const t = window.setInterval(() => {
      prefabsApi.previewsStatus(sid).then(finishRender).catch(() => setRendering(false));
    }, 1500);
    return () => window.clearInterval(t);
  }, [rendering, sid, finishRender]);
  useEffect(() => { prefabsApi.previewsStatus(sid).then((j) => setRendering(j.running)).catch(() => {}); }, [sid]);
  const renderPreviews = async (force: boolean) => {
    try {
      const job = await prefabsApi.renderPreviews(sid, force);
      setRendering(job.running);
    } catch (e) {
      actions.toast((e as Error).message, "error");
    }
  };

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (list?.prefabs ?? []).filter((p) => (group === null || p.group === group)
      && (!onlyEdited || p.edited > 0) && (!onlyVariants || p.variant_of)
      && (!q || p.name.toLowerCase().includes(q) || p.path.toLowerCase().includes(q)
        || p.components.some((c) => c.toLowerCase().includes(q))));
  }, [list, group, query, onlyEdited, onlyVariants]);

  const openPrefab = (path: string) => {
    clearMulti();
    setSelected(path);
    anchor.current = path;
  };
  const togglePrefab = (path: string, includeSingle = false) => {
    anchor.current = path;
    setMulti((current) => {
      const next = new Set(includeSingle && !current.size && selected ? [selected] : current);
      if (next.has(path)) next.delete(path); else next.add(path);
      return next;
    });
    setSelected(null);
  };
  const clickPrefab = (path: string, e: MouseEvent<HTMLButtonElement>) => {
    if (e.shiftKey) {
      const end = shown.findIndex((p) => p.path === path);
      const start = shown.findIndex((p) => p.path === anchor.current);
      anchor.current = path;
      const range = start < 0 ? [path] : shown.slice(Math.min(start, end), Math.max(start, end) + 1).map((p) => p.path);
      setMulti(new Set(range));
      setSelected(null);
    } else if (e.metaKey || e.ctrlKey) togglePrefab(path, true);
    else openPrefab(path);
  };

  const undoable = history.position > 0;
  const redoable = history.position < history.steps.length;

  const step = async (op: "undo" | "redo", force = false) => {
    try {
      await prefabsApi[op](sid, force);
      setConflict(null);
      await refreshAfterChange();
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
        {awaitingApproval && <span role="status" className="text-warn">Approve the Unity card in the Chat tab to start rendering</span>}
        <button className="btn py-0.5" onClick={(e) => renderPreviews(e.altKey)} disabled={rendering}
          title="Render a thumbnail of each changed prefab with Unity (asks first; Alt-click re-renders all)">
          {rendering ? <Loader2 size={13} className="animate-spin" /> : <ImageIcon size={13} />} {rendering ? "Rendering…" : "Render previews"}
        </button>
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
            {multi.size > 0 && <button className="btn btn-ghost self-start" disabled={!shown.length}
              onClick={() => setMulti((current) => new Set([...current, ...shown.map((p) => p.path)]))}>Select all shown</button>}
          </div>
          <div className="flex-1 min-h-0 overflow-y-auto p-1.5 flex flex-col gap-0.5">
            {shown.map((p) => (
              <PrefabRow key={p.path} p={p} sid={sid} v={previewV} active={p.path === singlePath && !multi.size}
                checked={multi.has(p.path)} multi={multi.size > 0} onToggle={() => togglePrefab(p.path)} onClick={(e) => clickPrefab(p.path, e)} />
            ))}
            {list && !shown.length && <div className="p-3 text-muted">No prefabs match.</div>}
          </div>
        </section>
        <Inspector sid={sid} detail={detail?.path === singlePath ? detail : null} summary={list?.prefabs.find((p) => p.path === singlePath) ?? null} v={previewV}
          history={history} undoable={undoable} redoable={redoable} onStep={step} conflict={conflict}
          onDismissConflict={() => setConflict(null)} onOpen={openPrefab} bulkPaths={bulkPaths} onBulkEdited={refreshAfterChange}
          onEdited={async (d) => {
            setDetail((current) => current?.path === d.path ? d : current);
            await Promise.all([loadList(), loadHistory()]);
            setPreviewV((v) => v + 1);
          }} />
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

function PrefabRow({ p, sid, v, active, checked, multi, onToggle, onClick }: {
  p: PrefabSummary; sid: string; v: number; active: boolean; checked: boolean; multi: boolean;
  onToggle: () => void; onClick: (e: MouseEvent<HTMLButtonElement>) => void;
}) {
  return (
    <div className={`group relative flex rounded border ${active || checked ? "border-action bg-[color-mix(in_srgb,var(--action)_8%,transparent)]" : "border-transparent hover:bg-sunken"}`}>
      <button onClick={onClick} aria-current={active || undefined}
        className="flex flex-1 min-w-0 items-center gap-2.5 text-left pl-2.5 pr-8 py-2 rounded">
        <Preview sid={sid} path={p.path} has={p.preview} size={36} v={v} />
        <span className="flex flex-col min-w-0">
          <span className="font-medium truncate">{p.name}{p.edited > 0 && <span className="text-warn font-normal"> · {p.edited} edit{p.edited === 1 ? "" : "s"}</span>}</span>
          <span className="text-[12px] text-muted truncate">
            {p.variant_of ? `variant of ${p.variant_of.name}` : p.components.filter((c) => c !== "Transform").slice(0, 3).join(", ") || p.folder}
          </span>
        </span>
      </button>
      <input type="checkbox" aria-label={`Select ${p.name}`} checked={checked} onChange={onToggle}
        className={`absolute right-2.5 top-1/2 -translate-y-1/2 ${multi ? "" : "opacity-0 group-hover:opacity-100 focus:opacity-100"}`} />
    </div>
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

function Inspector({ sid, detail, summary, v, history, undoable, redoable, onStep, conflict, onDismissConflict, onEdited, onOpen, bulkPaths, onBulkEdited }: {
  sid: string; detail: PrefabDetail | null; summary: PrefabSummary | null; v: number;
  history: { position: number; steps: HistoryStep[] }; undoable: boolean; redoable: boolean;
  onStep: (op: "undo" | "redo", force?: boolean) => void; conflict: { op: "undo" | "redo"; items: Conflict[] } | null;
  onDismissConflict: () => void; onEdited: (d: PrefabDetail) => void; onOpen: (path: string) => void;
  bulkPaths: string[]; onBulkEdited: () => Promise<void>;
}) {
  const [showHistory, setShowHistory] = useState(false);
  const next = history.steps.find((x) => !x.undone);
  const bulk = bulkPaths.length >= 2;
  return (
    <section aria-label={bulk ? "Bulk edit" : detail ? `Inspector: ${detail.name}` : "Inspector"} className="flex-1 min-w-0 flex flex-col min-h-0">
      <div className="px-5 py-3 border-b border-line flex items-center gap-3 flex-wrap relative">
        {detail && summary?.preview && <Preview sid={sid} path={detail.path} has size={72} v={v} />}
        <div className="flex flex-col gap-0.5 grow basis-[200px] min-w-0">
          <h2 className="m-0 text-[17px] font-semibold truncate">{bulk ? `Bulk edit · ${bulkPaths.length} prefabs` : detail?.name ?? "Select a prefab"}</h2>
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
        <BulkFields sid={sid} paths={bulkPaths} version={v} onEdited={onBulkEdited} />
        {!detail && !bulk && <p className="m-0 text-muted">Pick a prefab to see its values. Edits are written to the .prefab file and can be undone here.</p>}
        {detail && detail.objects[0] && (
          <ObjectComponents sid={sid} detail={detail} o={detail.objects[0]} onEdited={onEdited} />
        )}
        {detail && detail.objects.length > 1 && <Children sid={sid} detail={detail} onEdited={onEdited} />}
        {detail && <p className="m-0 text-faint text-[12px]">Read from the .prefab file by a script: no agent, no tokens. Unity reimports the file when its window gets focus.</p>}
      </div>
    </section>
  );
}

const BULK_LIMIT = 50;
const BULK_CONCURRENCY = 6;

function BulkFields({ sid, paths, version, onEdited }: {
  sid: string; paths: string[]; version: number; onEdited: () => Promise<void>;
}) {
  const [result, setResult] = useState<{ sid: string; paths: string[]; version: number; details?: PrefabDetail[]; error?: string }>();
  const [busy, setBusy] = useState(false);
  const [showBuiltins, setShowBuiltins] = useState(false);
  const workers = useRef<Promise<void>[]>([]);
  useEffect(() => {
    if (paths.length < 2 || paths.length > BULK_LIMIT) return;
    let active = true;
    let next = 0;
    const details: PrefabDetail[] = [];
    const batch = Array.from({ length: Math.min(paths.length, BULK_CONCURRENCY) }, (_, lane) => {
      const worker = (workers.current[lane] ?? Promise.resolve()).then(async () => {
        while (active && next < paths.length) {
          const i = next++;
          details[i] = await prefabsApi.detail(sid, paths[i]);
        }
      });
      // A replacement selection reuses each lane once its in-flight request settles.
      workers.current[lane] = worker.catch(() => {});
      return worker;
    });
    Promise.all(batch).then(() => {
      if (active) setResult({ sid, paths, version, details });
    }).catch((e) => {
      if (active) setResult({ sid, paths, version, error: editError(e) });
      active = false;
    });
    return () => { active = false; };
  }, [sid, paths, version]);

  const current = result?.sid === sid && result.paths === paths && result.version === version ? result : undefined;
  const groups = useMemo(() => current?.details && commonPrefabFields(current.details), [current]);
  if (paths.length < 2) return null;
  if (paths.length > BULK_LIMIT) return <p className="m-0 text-muted">Select 50 or fewer to bulk edit</p>;
  if (current?.error) return <p role="alert" className="m-0 text-bad">{current.error}</p>;
  if (!groups) return <p role="status" className="m-0 flex items-center gap-2 text-muted"><Loader2 size={14} className="animate-spin" /> Loading prefab details…</p>;

  const count = [...groups.values()].reduce((n, group) => n + group.slots.length, 0);
  const all = [...groups];
  const scriptGroups = all.filter(([, g]) => !g.component.builtin);
  const builtinGroups = all.filter(([, g]) => g.component.builtin);
  const fold = scriptGroups.length > 0 && builtinGroups.length > 0;
  const bulkOrdered = [...scriptGroups, ...(!fold || showBuiltins ? builtinGroups : [])];
  return (
    <fieldset disabled={busy} className="flex flex-col gap-3 border-0 p-0 m-0 min-w-0">
      <p className="m-0 text-muted">{count} {count === 1 ? "field" : "fields"} in common</p>
      {!count && <p className="m-0 text-muted">These prefabs share no editable fields</p>}
      {bulkOrdered.map(([key, { component, objectPath, slots }], i) => (<Fragment key={key}>
        <div className="border border-line rounded-md">
          <ComponentHeading c={component} objectPath={objectPath} />
          <div className="grid gap-3 p-3" style={FIELD_GRID}>
            {slots.map(({ key: fieldKey, label, kind, value, edits }) => {
              const commit = async (nextValue: string) => {
                if (busy) return;
                const changed = edits.filter((e) => e.value !== nextValue).map((e) => ({ ...e, value: nextValue }));
                if (!changed.length) return;
                setBusy(true);
                try {
                  await prefabsApi.editMany(sid, changed, `${changed.length} prefabs · ${label} → ${nextValue}`);
                  await onEdited();
                  actions.toast(`Set ${label} on ${changed.length} prefabs`);
                } finally {
                  setBusy(false);
                }
              };
              return kind === "bool"
                ? <label key={fieldKey} className="flex items-start gap-2 text-muted pt-5">
                    <BoolInput label={label} value={value} onCommit={commit} inlineError /> {label}
                    {value === null && <span className="text-faint text-[12px]">mixed</span>}
                  </label>
                : <label key={fieldKey} className="flex flex-col gap-1 text-muted min-w-0">
                    <span>{label}</span>
                    <TextInput label={label} kind={kind} value={value} onCommit={commit} />
                  </label>;
            })}
          </div>
        </div>
      </Fragment>))}
      {fold && <BuiltinToggle names={[...new Set(builtinGroups.map(([, g]) => g.component.type))]} open={showBuiltins}
        onToggle={() => setShowBuiltins((x) => !x)} />}
    </fieldset>
  );
}

const FIELD_LIMIT = 16;
const CHILD_LIMIT = 200;
const FIELD_GRID = { gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))" };

/** One object's components. Long components show FIELD_LIMIT fields until expanded, so a big prefab stays fast. */
function ObjectComponents({ sid, detail, o, onEdited }: {
  sid: string; detail: PrefabDetail; o: PrefabDetail["objects"][number]; onEdited: (d: PrefabDetail) => void;
}) {
  // Script values are what people tune, so scripts come first; built-in components fold away behind one button.
  const scripts = o.components.filter((c) => !c.builtin);
  const builtins = o.components.filter((c) => c.builtin);
  const fold = scripts.length > 0 && builtins.length > 0;
  const [showBuiltins, setShowBuiltins] = useState(!fold);
  const card = (c: PrefabDetail["objects"][number]["components"][number]) =>
    <ComponentCard key={c.file_id} sid={sid} detail={detail} c={c} onEdited={onEdited} />;
  return (
    <div className="flex flex-col gap-3">
      {scripts.map(card)}
      {fold && <BuiltinToggle names={builtins.map((c) => c.type)} open={showBuiltins} onToggle={() => setShowBuiltins((x) => !x)} />}
      {showBuiltins && builtins.map(card)}
      {!o.components.length && <div className="text-muted">No components.</div>}
    </div>
  );
}

function BuiltinToggle({ names, open, onToggle }: { names: string[]; open: boolean; onToggle: () => void }) {
  return (
    <button className="btn btn-ghost justify-start text-left text-muted" aria-expanded={open} onClick={onToggle}
      title={names.join(", ")}>
      {open ? "Hide" : "Show"} {names.length} built-in component{names.length === 1 ? "" : "s"}
      <span className="truncate text-faint">· {names.join(", ")}</span>
    </button>
  );
}

function ComponentCard({ sid, detail, c, onEdited }: {
  sid: string; detail: PrefabDetail; c: PrefabDetail["objects"][number]["components"][number]; onEdited: (d: PrefabDetail) => void;
}) {
  const [all, setAll] = useState(false);
  const fields = all ? c.fields : c.fields.slice(0, FIELD_LIMIT);
  return (
    <div className="border border-line rounded-md">
      <ComponentHeading c={c} />
      {fields.length ? (
        <div className="grid gap-3 p-3" style={FIELD_GRID}>
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

function ComponentHeading({ c, objectPath }: { c: PrefabDetail["objects"][number]["components"][number]; objectPath?: string }) {
  return (
    <div className="flex justify-between gap-2 px-3 py-2 bg-sunken border-b border-line rounded-t-md">
      <div className="min-w-0">
        <span className="font-semibold">{c.type}</span>
        {objectPath && <h3 className="m-0 text-[12px] font-normal text-muted truncate">{objectPath}</h3>}
      </div>
      <span className="text-muted truncate" title={c.script_path ?? undefined}>
        {c.builtin ? "built-in" : c.package ? `package ${c.package}` : [c.namespace, c.type].filter(Boolean).join(".")}
      </span>
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
  const commit = async (value: string, part?: string | null) => {
    onEdited((await prefabsApi.edit(sid, { path, file_id: fileId, key: f.key, part, value })).detail);
  };
  const note = f.edited ? <span className="text-warn text-[12px]">edited · was {f.edited.was}</span>
    : f.inherited ? <span className="text-faint text-[12px]">from {base ?? "base prefab"}</span>
    : f.override ? <span className="text-muted text-[12px]">overrides {base ?? "base"}</span> : null;
  const tone = f.edited ? "border-warn bg-[color-mix(in_srgb,var(--warn)_8%,transparent)]" : f.inherited ? "border-dashed text-muted" : "";
  if (f.kind === "bool" && f.editable) {
    return (
      <label className="flex items-center gap-2 text-muted pt-5">
        <BoolInput label={f.label} value={f.value} onCommit={commit} /> {f.label} {note}
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
            <TextInput key={k} kind={f.kind} value={f.parts![k]} label={`${f.label} ${k}`}
              className={tone} onCommit={(value) => commit(value, k)} prefix={k} />
          ))}
        </div>
      </fieldset>
    );
  }
  return (
    <label className="flex flex-col gap-1 text-muted min-w-0">
      <span>{f.label} {note}</span>
      {f.editable
        ? <TextInput kind={f.kind} value={f.value} label={f.label} className={tone} onCommit={(value) => commit(value, null)} />
        : <span className="input bg-sunken text-muted truncate" title={f.value}>{f.kind === "reference" ? refLabel(f.value) : f.value || "—"}</span>}
    </label>
  );
}

const refLabel = (v: string) => (/fileID: 0\b/.test(v) ? "None" : /guid: (\w{8})/.exec(v)?.[1] ? `asset ${/guid: (\w{8})/.exec(v)![1]}…` : v);

const editError = (e: unknown) => e instanceof ApiError ? e.message : String(e);

function BoolInput({ label, value, onCommit, inlineError }: {
  label: string; value: string | null; onCommit: (value: string) => Promise<void>; inlineError?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => { if (input.current) input.current.indeterminate = value === null; });
  return (
    <span className="inline-flex flex-col items-start gap-0.5">
      <input ref={input} type="checkbox" checked={value !== null && prefabBool(value)} disabled={busy} aria-label={label}
        aria-checked={value === null ? "mixed" : undefined} aria-invalid={!!error}
        onChange={async (e) => {
          setBusy(true);
          setError(null);
          try {
            await onCommit(e.target.checked ? "1" : "0");
          } catch (err) {
            if (inlineError) setError(editError(err));
            else actions.toast((err as Error).message, "error");
          } finally {
            setBusy(false);
          }
        }} />
      {error && <span role="alert" className="text-bad text-[12px]">{error}</span>}
    </span>
  );
}

function TextInput({ kind, value, label, className = "", onCommit, prefix }: {
  kind: PrefabField["kind"]; value: string | null; label: string;
  className?: string; onCommit: (value: string) => Promise<void>; prefix?: string;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setDraft(null); setError(null); }, [value]);
  const commit = async () => {
    if (draft === null || draft === value || busy) return;
    setBusy(true);
    try {
      await onCommit(draft);
      setError(null);
    } catch (e) {
      setError(editError(e));
    } finally {
      setDraft(null);
      setBusy(false);
    }
  };
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") (e.target as HTMLInputElement).blur();
    if (e.key === "Escape") { setDraft(null); setError(null); }
  };
  return (
    <span className="flex flex-col gap-0.5 min-w-0 flex-1">
      <span className="flex items-center gap-1 min-w-0">
        {prefix && <span className="text-faint text-[12px] uppercase">{prefix}</span>}
        <input className={`input ${className}`} aria-label={label} value={draft ?? value ?? ""} disabled={busy} aria-invalid={!!error}
          placeholder={value === null ? "mixed" : undefined} inputMode={kind === "string" ? "text" : "decimal"}
          onChange={(e) => setDraft(e.target.value)} onBlur={commit} onKeyDown={onKey} />
      </span>
      {error && <span role="alert" className="text-bad text-[12px]">{error}</span>}
    </span>
  );
}
