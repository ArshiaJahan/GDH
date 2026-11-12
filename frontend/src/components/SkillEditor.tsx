// The Skills page's SKILL.md editor: Monaco with an inline frontmatter check, ⌘S to save, a
// guard against losing unsaved changes, the skill's other files, and read-only built-ins with
// "Customize". Loaded lazily (with Monaco) only when a skill is opened.
import Editor, { type OnMount } from "@monaco-editor/react";
import { AlertCircle, AlertTriangle, CheckCircle2, Copy, FileText, Lock, Save } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, get, post } from "../lib/api";
import { monaco, useMonacoTheme } from "../lib/monaco";
import { NAME_RE, validateSkill, type Issue } from "../lib/skillValidate";
import { actions } from "../lib/store";
import { Modal, ModalFooter } from "./ui";

type SkillInfo = { name: string; source: string; path: string; content: string; overrides_builtin?: boolean };
type SkillFile = { path: string; size: number };
type FileMeta = { binary: boolean; truncated: boolean; editable: boolean; size: number };

const SKILL_MD = "SKILL.md";
const NEW_SKILL = `---
name: my-skill
description: One sentence on what this skill does and when to use it.
---

# My skill

What to do, step by step.
`;

const LANGS: Record<string, string> = {
  md: "markdown", markdown: "markdown", py: "python", sh: "shell", bash: "shell", zsh: "shell", js: "javascript", mjs: "javascript",
  cjs: "javascript", ts: "typescript", tsx: "typescript", jsx: "javascript", json: "json", yaml: "yaml", yml: "yaml", toml: "ini",
  ini: "ini", cs: "csharp", html: "html", htm: "html", css: "css", xml: "xml", sql: "sql", rb: "ruby", go: "go", rs: "rust",
  swift: "swift", java: "java", kt: "kotlin", c: "c", h: "cpp", cpp: "cpp", hpp: "cpp", lua: "lua", ps1: "powershell", txt: "plaintext",
};
const langOf = (path: string) => LANGS[path.split(".").pop()?.toLowerCase() ?? ""] ?? "plaintext";
const fmtSize = (n: number) => (n < 1024 ? `${n} B` : n < 1024 ** 2 ? `${(n / 1024).toFixed(0)} KB` : `${(n / 1024 ** 2).toFixed(1)} MB`);

export default function SkillEditor({ name: initialName, existing, onClose, onSaved }: {
  /** null: a new skill */
  name: string | null;
  /** names already installed, to warn before a new skill replaces one */
  existing: string[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const theme = useMonacoTheme();
  const [skill, setSkill] = useState<SkillInfo | null>(null);
  const [files, setFiles] = useState<SkillFile[]>([]);
  const [current, setCurrent] = useState(SKILL_MD);
  const [meta, setMeta] = useState<FileMeta | null>(null);
  const [text, setText] = useState(initialName ? "" : NEW_SKILL);
  const [saved, setSaved] = useState(initialName ? "" : NEW_SKILL);
  const [loading, setLoading] = useState(!!initialName);
  const [busy, setBusy] = useState(false);
  const editorRef = useRef<Parameters<OnMount>[0] | null>(null);

  const isNew = !skill && !initialName;
  const builtin = skill?.source === "builtin";
  const onSkillMd = current === SKILL_MD;
  const readOnly = builtin || (!onSkillMd && (!meta || meta.binary || meta.truncated || !meta.editable));
  const dirty = !readOnly && text !== saved;
  const check = useMemo(() => (onSkillMd ? validateSkill(text, { folder: skill?.name, existing }) : null), [onSkillMd, text, skill?.name, existing]);
  const errors = check?.issues.filter((i) => i.severity === "error") ?? [];

  const loadFiles = async (n: string) => setFiles((await get(`/skills/${n}/files`)).files);
  useEffect(() => {
    if (!initialName) return;
    (async () => {
      try {
        const s = await get<SkillInfo>(`/skills/${initialName}`);
        setSkill(s); setText(s.content); setSaved(s.content);
        await loadFiles(s.name);
      } catch (e: any) { actions.toast(e.message, "error"); onClose(); } finally { setLoading(false); }
    })();
  }, [initialName]);

  // Leaving the app (reload, closing the window) with unsaved changes asks first.
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const discardOk = (what: string) => !dirty || confirm(`Discard your unsaved changes to ${what}?`);
  const requestClose = () => { if (discardOk(current)) onClose(); };

  const openFile = async (path: string) => {
    if (path === current || !skill || !discardOk(current)) return;
    try {
      if (path === SKILL_MD) {
        const s = await get<SkillInfo>(`/skills/${skill.name}`);
        setMeta(null); setText(s.content); setSaved(s.content);
      } else {
        const f = await get(`/skills/${skill.name}/file?${new URLSearchParams({ path })}`);
        setMeta({ binary: f.binary, truncated: f.truncated, editable: f.editable, size: f.size });
        setText(f.content); setSaved(f.content);
      }
      setCurrent(path);
    } catch (e: any) { actions.toast(e.message, "error"); }
  };

  const save = async () => {
    if (readOnly || busy) return;
    if (!onSkillMd) {
      setBusy(true);
      try {
        const f = await api(`/skills/${skill!.name}/file?${new URLSearchParams({ path: current })}`, { method: "PUT", body: { content: text } });
        setSaved(f.content); setText(f.content);
        actions.toast(`Saved ${current}`);
        loadFiles(skill!.name);
      } catch (e: any) { actions.toast(e.message, "error"); } finally { setBusy(false); }
      return;
    }
    const name = skill?.name ?? check?.name ?? text.match(/^name:\s*([a-z0-9-]+)/m)?.[1];
    if (!name || !NAME_RE.test(name)) return actions.toast("Give the skill a name: lowercase letters, digits and dashes.", "error");
    if (errors.length && !confirm(`SKILL.md has ${errors.length} problem${errors.length > 1 ? "s" : ""}:\n\n${errors.map((e) => `• line ${e.line}: ${e.message}`).join("\n")}\n\nSave anyway?`)) return;
    if (isNew && existing.includes(name) && !confirm(`A skill named "${name}" already exists. Replace it with this one?`)) return;
    setBusy(true);
    try {
      const s = await api<SkillInfo>(`/skills/${name}`, { method: "PUT", body: { content: text } });
      setSkill(s); setText(s.content); setSaved(s.content);
      actions.toast(`Saved ${name}`);
      onSaved();
      loadFiles(name);
    } catch (e: any) { actions.toast(e.message, "error"); } finally { setBusy(false); }
  };
  const saveRef = useRef(save);
  saveRef.current = save;

  const customize = async () => {
    if (!skill) return;
    setBusy(true);
    try {
      const s = await post<SkillInfo>(`/skills/${skill.name}/customize`);
      setSkill(s);
      if (onSkillMd) { setText(s.content); setSaved(s.content); }
      else setMeta((m) => (m ? { ...m, editable: true } : m));
      await loadFiles(s.name);
      actions.toast(`${s.name} is now your own copy; it takes precedence over the built-in.`);
      onSaved();
      requestAnimationFrame(() => editorRef.current?.focus());
    } catch (e: any) { actions.toast(e.message, "error"); } finally { setBusy(false); }
  };

  // ⌘S anywhere in the dialog (the editor has its own binding below).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s" && !e.defaultPrevented) { e.preventDefault(); saveRef.current(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const onMount: OnMount = (ed, m) => {
    editorRef.current = ed;
    ed.addCommand(m.KeyMod.CtrlCmd | m.KeyCode.KeyS, () => saveRef.current());
    applyMarkers(check?.issues ?? []);
  };
  const applyMarkers = (issues: Issue[]) => {
    const model = editorRef.current?.getModel();
    if (!model) return;
    const last = model.getLineCount();
    monaco.editor.setModelMarkers(model, "skill-frontmatter", issues.map((i) => {
      const line = Math.min(i.line, last), endLine = Math.min(i.endLine ?? i.line, last);
      // a span of a character or two (where YAML noticed the problem) underlines the rest of the line instead
      const ranged = i.endCol != null && (endLine > line || i.endCol > (i.col ?? 1) + 2);
      return {
        severity: i.severity === "error" ? monaco.MarkerSeverity.Error : monaco.MarkerSeverity.Warning,
        message: i.message, startLineNumber: line, startColumn: Math.min(i.col ?? 1, model.getLineMaxColumn(line)),
        endLineNumber: ranged ? endLine : line, endColumn: ranged ? i.endCol! : model.getLineMaxColumn(line),
      };
    }));
  };
  useEffect(() => { applyMarkers(check?.issues ?? []); }, [check, current]);

  const goTo = (i: Issue) => {
    const ed = editorRef.current;
    if (!ed) return;
    ed.revealLineInCenter(i.line);
    ed.setPosition({ lineNumber: i.line, column: i.col ?? 1 });
    ed.focus();
  };

  const title = isNew ? "New skill" : `${skill?.name ?? initialName} · skill`;
  const kind = builtin ? "built in" : skill?.overrides_builtin ? "your copy of a built-in" : isNew ? "new" : "yours";
  return (
    <Modal title={title} onClose={requestClose} wide>
      <div className="flex items-center gap-2 mb-2 text-[13px]">
        <FileText size={14} className="text-muted" />
        <span className="font-mono">{current}</span>
        <span className="chip">{kind}</span>
        {readOnly && <span className="inline-flex items-center gap-1 text-muted text-[12px]"><Lock size={12} /> read-only</span>}
        {dirty && <span className="inline-flex items-center gap-1.5 text-[12px]" style={{ color: "var(--warn)" }} aria-label="Unsaved changes"><span className="size-2 rounded-full" style={{ background: "var(--warn)" }} /> Unsaved changes</span>}
      </div>

      <div className="flex border border-line rounded overflow-hidden" style={{ height: "56vh" }}>
        <nav className="w-60 shrink-0 border-r border-line overflow-y-auto scroll-thin bg-sunken/40 text-[12.5px] py-1" aria-label="Skill files">
          <FileButton path={SKILL_MD} label={SKILL_MD} active={onSkillMd} onClick={() => openFile(SKILL_MD)} />
          {byFolder(files).map(([dir, list]) => (
            <div key={dir}>
              {dir && <div className="px-2.5 pt-2 pb-0.5 text-[11px] text-faint font-mono truncate" title={dir}>{dir}/</div>}
              {list.map((f) => <FileButton key={f.path} path={f.path} label={dir ? f.path.slice(dir.length + 1) : f.path} indent={!!dir} size={f.size} active={current === f.path} onClick={() => openFile(f.path)} />)}
            </div>
          ))}
          {isNew && <p className="px-2.5 py-2 text-muted text-[12px]">Save the skill first; then add references/, scripts/ or templates/ to its folder.</p>}
          {!isNew && !files.length && !loading && <p className="px-2.5 py-2 text-faint text-[12px]">No other files.</p>}
        </nav>
        <div className="flex-1 min-w-0" onKeyDown={(e) => e.key === "Escape" && e.stopPropagation() /* Escape is the editor's (find, suggestions), not the dialog's */}>
          {loading ? <p className="p-3 text-muted">Loading…</p>
            : meta?.binary ? <p className="p-3 text-muted">{current} is a binary file ({fmtSize(meta.size)}); it isn't shown here.</p>
            : (
              <Editor key={current} height="100%" language={onSkillMd ? "markdown" : langOf(current)} value={text} theme={theme}
                onChange={(v) => setText(v ?? "")} onMount={onMount}
                options={{ readOnly, readOnlyMessage: { value: builtin ? "Built-in skills are read-only. Press **Customize** to edit your own copy." : "This file can't be edited here." },
                           wordWrap: "on", minimap: { enabled: false }, fontSize: 12.5, fontFamily: "IBM Plex Mono, Menlo, monospace", lineNumbersMinChars: 3,
                           scrollBeyondLastLine: false, renderLineHighlight: "line", tabSize: 2, unicodeHighlight: { ambiguousCharacters: false }, automaticLayout: true }} />
            )}
        </div>
      </div>

      {onSkillMd && check && !loading && (
        <div className="mt-2 text-[12.5px]" role="status" aria-label="Frontmatter check">
          {check.issues.length === 0 ? (
            <div className="flex items-center gap-1.5 text-muted"><CheckCircle2 size={13} style={{ color: "var(--ok)" }} /> Frontmatter OK: name and description are valid{check.description ? ` (description ${[...check.description].length}/1024)` : ""}.</div>
          ) : (
            <ul className="max-h-28 overflow-y-auto scroll-thin space-y-0.5">
              {check.issues.map((i, n) => (
                <li key={n}>
                  <button className="flex items-start gap-1.5 text-left hover:underline" onClick={() => goTo(i)}>
                    {i.severity === "error" ? <AlertCircle size={13} className="mt-[3px] shrink-0 text-bad" /> : <AlertTriangle size={13} className="mt-[3px] shrink-0" style={{ color: "var(--warn)" }} />}
                    <span><span className="text-muted tabular-nums">Line {i.line}:</span> {i.message}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {!onSkillMd && meta?.truncated && <p className="mt-2 text-[12.5px] text-muted">This file is larger than 200 KB; only its start is shown, read-only.</p>}
      <ModalFooter className="!mt-3" start={
        builtin ? "Built-in skills are read-only. Customize copies it, with its files, to your skills folder; your copy takes precedence over the built-in."
          : skill?.overrides_builtin ? "Your copy takes precedence over the built-in skill of the same name."
          : "Saved to your skills folder. The frontmatter name is always the folder name."}>
        <button className="btn" onClick={requestClose}>Close</button>
        {builtin ? (
          <button className="btn btn-primary" onClick={customize} disabled={busy || loading} title="Copy this skill and its files to your skills folder, where your copy takes precedence">
            <Copy size={14} /> Customize
          </button>
        ) : (
          <button className="btn btn-primary" onClick={save} disabled={busy || readOnly || (!dirty && !isNew)} title="Save (⌘S)">
            <Save size={14} /> Save <span className="opacity-70 text-[11px]">⌘S</span>
          </button>
        )}
      </ModalFooter>
    </Modal>
  );
}

/** Files grouped by their folder (references/, scripts/, …), top-level files first. */
function byFolder(files: SkillFile[]): [string, SkillFile[]][] {
  const groups = new Map<string, SkillFile[]>();
  for (const f of files) {
    const dir = f.path.includes("/") ? f.path.slice(0, f.path.lastIndexOf("/")) : "";
    groups.set(dir, [...(groups.get(dir) ?? []), f]);
  }
  return [...groups.entries()].sort(([a], [b]) => (a === "" ? -1 : b === "" ? 1 : a.localeCompare(b)));
}

function FileButton({ path, label, indent, size, active, onClick }: { path: string; label: string; indent?: boolean; size?: number; active: boolean; onClick: () => void }) {
  return (
    <button className={`w-full flex items-center gap-2 ${indent ? "pl-4" : "pl-2.5"} pr-2.5 py-1 text-left font-mono ${active ? "bg-sunken font-medium" : "hover:bg-sunken"}`} aria-current={active || undefined} onClick={onClick} title={path}>
      <span className="truncate flex-1">{label}</span>
      {size != null && <span className="text-faint text-[11px] tabular-nums shrink-0">{fmtSize(size)}</span>}
    </button>
  );
}
