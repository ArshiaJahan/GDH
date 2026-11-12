// Checks a SKILL.md's frontmatter as you type (the Skills page editor). Lines are 1-based lines of
// the whole file, so they can become editor markers. Mirrors what the backend and Claude Code expect:
// a lowercase name that is the skill's folder, and a description of at most 1024 characters.
import { LineCounter, parseDocument, isMap, isScalar } from "yaml";

export type Issue = { severity: "error" | "warning"; message: string; line: number; col?: number; endLine?: number; endCol?: number };
export type SkillCheck = { issues: Issue[]; name?: string; description?: string };

export const NAME_RE = /^[a-z0-9][a-z0-9-]{0,63}$/;
export const MAX_DESCRIPTION = 1024;
const FM = /^---[ \t]*\r?\n([\s\S]*?)\r?\n---[ \t]*(?:\r?\n|$)/;

/** folder: the skill's folder name (unset for a new skill); existing: names already installed. */
export function validateSkill(text: string, opts: { folder?: string; existing?: string[] } = {}): SkillCheck {
  const issues: Issue[] = [];
  const m = FM.exec(text);
  if (!m) {
    issues.push(/^---[ \t]*\r?\n/.test(text)
      ? { severity: "error", line: 1, message: "The frontmatter isn't closed: add a line with --- after its last key." }
      : { severity: "error", line: 1, message: "SKILL.md should start with frontmatter: a --- line, name: and description:, then ---." });
    return { issues };
  }
  const lc = new LineCounter();
  const doc = parseDocument(m[1], { lineCounter: lc, prettyErrors: false, uniqueKeys: true });
  // The frontmatter starts on the file's second line.
  const at = (offset: number) => { const p = lc.linePos(offset); return { line: p.line + 1, col: p.col }; };
  const span = (range?: readonly number[] | null) => {
    if (!range) return { line: 2 };
    const a = at(range[0]), b = at(range[1] ?? range[0]);
    return { line: a.line, col: a.col, endLine: b.line, endCol: b.col };
  };
  for (const e of doc.errors) {
    issues.push({ severity: "error", message: `YAML: ${e.message.split("\n")[0]}`, ...span(e.pos) });
  }
  for (const w of doc.warnings) {
    issues.push({ severity: "warning", message: `YAML: ${w.message.split("\n")[0]}`, ...span(w.pos) });
  }
  if (doc.errors.length) return { issues };

  const root = doc.contents;
  if (!isMap(root)) {
    issues.push({ severity: "error", line: 2, message: "The frontmatter must be key: value lines (name:, description:, …)." });
    return { issues };
  }
  const pair = (key: string) => root.items.find((p) => isScalar(p.key) && p.key.value === key);
  const fmEnd = 1 + m[1].split(/\r?\n/).length + 1; // the closing --- line

  let name: string | undefined;
  const np = pair("name");
  if (!np || np.value == null || (isScalar(np.value) && (np.value.value == null || String(np.value.value).trim() === ""))) {
    issues.push({ severity: "error", line: np ? span((np.key as any)?.range).line : fmEnd, message: `Add name:${opts.folder ? ` ${opts.folder}` : " (lowercase letters, digits and dashes)"}.` });
  } else if (!isScalar(np.value) || typeof np.value.value !== "string") {
    issues.push({ severity: "error", ...span((np.value as any).range), message: "name must be a single line of text." });
  } else {
    name = np.value.value.trim();
    const where = span(np.value.range);
    if (!NAME_RE.test(name)) {
      issues.push({ severity: "error", ...where, message: `name "${name}" must be lowercase letters, digits and dashes (at most 64), starting with a letter or digit.` });
    } else if (opts.folder && name !== opts.folder) {
      issues.push({ severity: "error", ...where, message: `name must match the skill's folder, "${opts.folder}" (saving would set it back).` });
    } else if (!opts.folder && opts.existing?.includes(name)) {
      issues.push({ severity: "warning", ...where, message: `A skill named "${name}" already exists; saving replaces it with this one.` });
    }
  }

  let description: string | undefined;
  const dp = pair("description");
  if (!dp || dp.value == null || (isScalar(dp.value) && (dp.value.value == null || String(dp.value.value).trim() === ""))) {
    issues.push({ severity: "error", line: dp ? span((dp.key as any)?.range).line : fmEnd, message: "Add description: one or two sentences on what the skill does and when to use it." });
  } else if (!isScalar(dp.value) || typeof dp.value.value !== "string") {
    issues.push({ severity: "error", ...span((dp.value as any).range), message: "description must be text, not a list or mapping." });
  } else {
    description = dp.value.value;
    const n = [...description].length;
    if (n > MAX_DESCRIPTION) {
      issues.push({ severity: "error", ...span(dp.value.range), message: `description is ${n} characters; the limit is ${MAX_DESCRIPTION}.` });
    }
  }

  if (!text.slice(m[0].length).trim()) {
    issues.push({ severity: "warning", line: fmEnd, message: "There are no instructions after the frontmatter." });
  }
  return { issues, name, description };
}
