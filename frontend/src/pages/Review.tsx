// The Review desk: review an Eval Forge trial like a teammate's PR (backend features/review_desk.py, REST
// /api/review). Trajectory, diff and hidden-test results side by side; a rubric review, failure tags, A/B
// preferences, an optional model pre-review and a JSONL dataset export. First draft by GLM-5.3-Flash, reviewed
// and fixed by hand.
import { useEffect, useMemo, useState } from "react";
import { Check, Download, GitCompare, Sparkles, X } from "lucide-react";
import { get, post } from "../lib/api";
import { actions } from "../lib/store";
import { Empty } from "../components/ui";

type Review = {
  id: string;
  key: string;
  reviewer: string;
  source: "human" | `llm:${string}`;
  verdict: "accept" | "reject";
  scores: { correctness: number; maintainability: number; test_quality: number };
  failure_mode: string;
  tags: string[];
  notes: string;
  created_at: number;
};

type Pref = {
  id: string;
  task: string;
  a: string;
  b: string;
  winner: "a" | "b" | "tie";
  reason: string;
  reviewer: string;
  created_at: number;
};

type Step = {
  i: number;
  kind: "text" | "thinking" | "tool" | "system";
  tool: string | null;
  title: string;
  input: string | null;
  output: string | null;
  is_error: boolean;
  ts: string | null;
};

type Rubric = {
  id: "correctness" | "maintainability" | "test_quality";
  label: string;
  question: string;
  anchors: { "1": string; "3": string; "5": string };
};

type Tag = { id: string; label: string; description: string };

type RunSummary = {
  dir: string;
  name: string;
  trials: number;
  passed: number;
  agents: string[];
  reviews: number;
};

type RunTrial = {
  key: string;
  task: string;
  agent: string;
  trial: number;
  passed: boolean;
  blame: string | null;
  reason: string | null;
  cost_usd: number;
  wall_s: number;
  tool_calls: number;
  human: Review | null;
  llm: Review | null;
};

type RunDetail = {
  dir: string;
  rubric: Rubric[];
  taxonomy: Tag[];
  trials: RunTrial[];
};

type Grade = {
  passed: boolean;
  steps: { name: string; kind: string; passed: boolean; exit: number | null; output: string }[];
};

type TrialDetail = {
  key: string;
  task: string;
  agent: string;
  trial: number;
  passed: boolean;
  blame: string | null;
  reason: string | null;
  prompt: string;
  diff: string;
  grade: Grade;
  steps: Step[];
  reviews: Review[];
  preferences: Pref[];
};

type Agreement = {
  n: number;
  verdict_agreement: number | null;
  kappa: number | null;
  score_mae: Record<string, number | null>;
  within_one: number | null;
  failure_mode_agreement: number | null;
  pairs: unknown[];
};

export function diffLines(diff: string): { text: string; kind: "add" | "del" | "hunk" | "file" | "ctx" }[] {
  return diff.split("\n").filter((l, i, arr) => !(l === "" && i === arr.length - 1)).map((text) => {
    if (text.startsWith("+++") || text.startsWith("---") || text.startsWith("diff --git")) return { text, kind: "file" as const };
    if (text.startsWith("@@")) return { text, kind: "hunk" as const };
    if (text.startsWith("+")) return { text, kind: "add" as const };
    if (text.startsWith("-")) return { text, kind: "del" as const };
    return { text, kind: "ctx" as const };
  });
}

export function verdictColor(v: "accept" | "reject" | null | undefined): string {
  if (v === "accept") return "var(--ok)";
  if (v === "reject") return "var(--bad)";
  return "var(--muted)";
}

const REVIEWER_KEY = "gdw.review.reviewer";

function loadReviewer(): string {
  try {
    return localStorage.getItem(REVIEWER_KEY) ?? "";
  } catch {
    return "";
  }
}

function saveReviewer(name: string) {
  try {
    localStorage.setItem(REVIEWER_KEY, name);
  } catch {
    /* ignore */
  }
}

const emptyScores = { correctness: 0, maintainability: 0, test_quality: 0 };

export function ReviewPage() {
  const [root, setRoot] = useState("evals/runs");
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [runDir, setRunDir] = useState("");
  const [run, setRun] = useState<RunDetail | null>(null);
  const [agreement, setAgreement] = useState<Agreement | null>(null);
  const [trialKey, setTrialKey] = useState("");
  const [trial, setTrial] = useState<TrialDetail | null>(null);
  const [openStep, setOpenStep] = useState<number | null>(null);

  // review form state
  const [reviewer, setReviewer] = useState(loadReviewer);
  const [verdict, setVerdict] = useState<"accept" | "reject" | "">("");
  const [scores, setScores] = useState<Record<string, number>>(emptyScores);
  const [failureMode, setFailureMode] = useState("none");
  const [tags, setTags] = useState<string[]>([]);
  const [notes, setNotes] = useState("");
  const [proposedBy, setProposedBy] = useState<string | null>(null);

  // compare mode
  const [compareMode, setCompareMode] = useState(false);
  const [compareKey, setCompareKey] = useState("");

  const loadRuns = async (r: string) => {
    if (!r.trim()) return;
    try {
      const data = await get<{ root: string; runs: RunSummary[] }>(`/review/runs?root=${encodeURIComponent(r)}`);
      setRuns(data.runs);
    } catch (e) {
      actions.toast(`Couldn't list runs in ${r}: ${e instanceof Error ? e.message : e}`);
    }
  };

  useEffect(() => {
    loadRuns(root);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadRun = async (dir: string) => {
    setRunDir(dir);
    setTrialKey("");
    setTrial(null);
    setAgreement(null);
    if (!dir) return;
    try {
      const [d, a] = await Promise.all([
        get<RunDetail>(`/review/run?dir=${encodeURIComponent(dir)}`),
        get<Agreement>(`/review/agreement?dir=${encodeURIComponent(dir)}`),
      ]);
      setRun(d);
      setAgreement(a);
    } catch (e) {
      actions.toast(`Couldn't open the run: ${e instanceof Error ? e.message : e}`);
    }
  };

  const loadTrial = async (key: string) => {
    setTrialKey(key);
    setOpenStep(null);
    setProposedBy(null);
    resetForm();
    if (!runDir || !key) return;
    try {
      const d = await get<TrialDetail>(`/review/trial?dir=${encodeURIComponent(runDir)}&key=${encodeURIComponent(key)}`);
      setTrial(d);
      const existing = d.reviews.find((r) => r.source === "human");
      if (existing) fillForm(existing);
    } catch (e) {
      actions.toast(`Couldn't open the trial: ${e instanceof Error ? e.message : e}`);
    }
  };

  const resetForm = () => {
    setVerdict("");
    setScores(emptyScores);
    setFailureMode("none");
    setTags([]);
    setNotes("");
  };

  const fillForm = (r: Review) => {
    if (r.source === "human") setReviewer(r.reviewer || reviewer); // a model's proposal keeps the person's name
    setVerdict(r.verdict);
    setScores({ correctness: r.scores.correctness, maintainability: r.scores.maintainability, test_quality: r.scores.test_quality });
    setFailureMode(r.failure_mode || "none");
    setTags(r.tags || []);
    setNotes(r.notes || "");
  };

  const saveReview = async () => {
    if (!runDir || !trial) return;
    saveReviewer(reviewer);
    try {
      await post<Review>("/review/reviews", {
        dir: runDir,
        key: trial.key,
        reviewer,
        verdict,
        scores,
        failure_mode: failureMode,
        tags,
        notes,
      });
      actions.toast("Review saved");
      setProposedBy(null);
      await loadRun(runDir);
      await loadTrial(trial.key);
    } catch (e) {
      actions.toast(`Couldn't save the review: ${e instanceof Error ? e.message : e}`);
    }
  };

  const askModel = async () => {
    if (!runDir || !trial) return;
    try {
      const r = await post<Review>("/review/prereview", { dir: runDir, key: trial.key });
      fillForm(r);
      setProposedBy(r.source);
    } catch (e) {
      actions.toast(`The model couldn't review it: ${e instanceof Error ? e.message : e}`);
    }
  };

  const compareTrials = useMemo(() => {
    if (!run || !trial) return [];
    return run.trials.filter((t) => t.task === trial.task && t.key !== trial.key);
  }, [run, trial]);

  const [compareDetail, setCompareDetail] = useState<TrialDetail | null>(null);

  const loadCompare = async (key: string) => {
    setCompareKey(key);
    if (!runDir || !key) {
      setCompareDetail(null);
      return;
    }
    try {
      const d = await get<TrialDetail>(`/review/trial?dir=${encodeURIComponent(runDir)}&key=${encodeURIComponent(key)}`);
      setCompareDetail(d);
    } catch (e) {
      actions.toast(`Couldn't open that trial: ${e instanceof Error ? e.message : e}`);
    }
  };

  const savePref = async (winner: "a" | "b" | "tie", reasonInput: string) => {
    if (!runDir || !trial || !compareKey) return;
    try {
      await post<Pref>("/review/preferences", {
        dir: runDir,
        task: trial.task,
        a: trial.key,
        b: compareKey,
        winner,
        reason: reasonInput,
        reviewer,
      });
      actions.toast("Preference saved");
    } catch (e) {
      actions.toast(`Couldn't save the preference: ${e instanceof Error ? e.message : e}`);
    }
  };

  const exportDataset = async () => {
    if (!runDir) return;
    try {
      const r = await post<{ path: string; reviews: number; preferences: number }>("/review/export", { dir: runDir });
      actions.toast(`Exported to ${r.path}`);
    } catch (e) {
      actions.toast(`Export failed: ${e instanceof Error ? e.message : e}`);
    }
  };

  const toggleTag = (id: string) => {
    setTags((t) => (t.includes(id) ? t.filter((x) => x !== id) : [...t, id]));
  };

  const compare = compareMode && compareDetail && trial;
  const complete = !!reviewer.trim() && !!verdict && (run?.rubric ?? []).every((r) => (scores[r.id] ?? 0) >= 1);

  return (
    <div className="h-full overflow-y-auto scroll-thin">
      <div className="max-w-[1400px] mx-auto px-6 py-5">
        <h1 className="text-lg font-semibold">Review desk</h1>

        <div className="flex items-center gap-2 mt-3">
          <input
            aria-label="Runs root"
            className="border border-line rounded-md px-2 py-1 text-[13px]"
            value={root}
            onChange={(e) => setRoot(e.target.value)}
            onBlur={() => loadRuns(root)}
          />
          <select
            aria-label="Run"
            className="border border-line rounded-md px-2 py-1 text-[13px]"
            value={runDir}
            onChange={(e) => loadRun(e.target.value)}
          >
            <option value="">Select a run…</option>
            {runs.map((r) => (
              <option key={r.dir} value={r.dir}>
                {r.name} ({r.passed}/{r.trials})
              </option>
            ))}
          </select>
          <button className="btn" onClick={() => loadRuns(root)}>
            Refresh
          </button>
          <div className="text-[12px] text-muted tabular-nums">
            {agreement && agreement.n > 0 && (
              <span>
                LLM vs human: {agreement.n} trials, verdict {Math.round((agreement.verdict_agreement ?? 0) * 100)}%
                {agreement.kappa != null ? `, kappa ${agreement.kappa.toFixed(2)}` : ""}
              </span>
            )}
          </div>
          <div className="flex-1" />
          {compareTrials.length > 0 && (
            <button className="btn btn-ghost" onClick={() => setCompareMode((c) => !c)}>
              <GitCompare size={14} /> Compare
            </button>
          )}
          <button className="btn btn-ghost" onClick={exportDataset}>
            <Download size={14} /> Export dataset
          </button>
        </div>

        {compareMode && trial && (
          <div className="mt-3 flex items-center gap-2">
            <select
              aria-label="Compare with"
              className="border border-line rounded-md px-2 py-1 text-[13px]"
              value={compareKey}
              onChange={(e) => loadCompare(e.target.value)}
            >
              <option value="">Pick trial to compare…</option>
              {compareTrials.map((t) => (
                <option key={t.key} value={t.key}>
                  {t.task} #{t.trial} ({t.agent}) {t.passed ? "pass" : "fail"}
                </option>
              ))}
            </select>
          </div>
        )}

        <div className="grid grid-cols-[260px_1fr] gap-4 mt-4">
          <div className="surface border border-line rounded-md p-2 overflow-y-auto scroll-thin" style={{ height: "calc(100vh - 220px)" }}>
            {!run && <Empty>Select a run to see trials</Empty>}
            {run?.trials.map((t) => (
              <button
                key={t.key}
                aria-label={`${t.task} #${t.trial}`}
                className={`w-full text-left px-2 py-1.5 rounded-md text-[13px] ${t.key === trialKey ? "font-medium" : ""}`}
                onClick={() => loadTrial(t.key)}
              >
                <div className="flex items-center gap-2 min-w-0">
                  <span
                    className="inline-block w-2 h-2 rounded-full shrink-0"
                    style={{ background: t.passed ? "var(--ok)" : "var(--bad)" }}
                  />
                  <span className="font-medium truncate" title={t.task}>{t.task}</span>
                  <span className="text-muted tabular-nums">#{t.trial}</span>
                  <span className="text-muted text-[12px]">{t.agent}</span>
                </div>
                {t.blame && <div className="text-[12px] text-muted">{t.blame}</div>}
                <div className="flex gap-1 mt-1">
                  {t.human && (
                    <span className="chip text-[12px]" style={{ color: verdictColor(t.human.verdict) }}>
                      Human: {t.human.verdict}
                    </span>
                  )}
                  {t.llm && (
                    <span className="chip text-[12px]" style={{ color: verdictColor(t.llm.verdict) }}>
                      LLM: {t.llm.verdict}
                    </span>
                  )}
                </div>
              </button>
            ))}
          </div>

          <div className="min-w-0">
            {!trial && <Empty>Pick a trial from the list</Empty>}
            {trial && (
              <>
                {compare ? (
                  <div className="grid grid-cols-2 gap-3" style={{ height: "calc(100vh - 220px)" }}>
                    <DiffPanel title={`A: ${trial.task} #${trial.trial}`} diff={trial.diff} />
                    <DiffPanel title={`B: ${compareDetail.task} #${compareDetail.trial}`} diff={compareDetail.diff} />
                  </div>
                ) : (
                  <div className="grid grid-cols-3 gap-3" style={{ height: "calc(100vh - 220px)" }}>
                    <TrajectoryPanel
                      steps={trial.steps}
                      openStep={openStep}
                      setOpenStep={setOpenStep}
                    />
                    <DiffPanel title="Diff" diff={trial.diff} />
                    <TestsPanel trial={trial} />
                  </div>
                )}

                {compare && (
                  <PreferenceBar
                    disabled={!compareKey}
                    onSave={savePref}
                  />
                )}

                <div className="mt-4 surface border border-line rounded-md p-4" aria-label="Review form">
                  <div className="flex items-center gap-3">
                    <h2 className="font-medium text-[13px]">Review</h2>
                    {proposedBy && (
                      <span className="chip text-[12px]" style={{ color: "var(--action)" }}>
                        Proposed by {proposedBy}
                      </span>
                    )}
                  </div>
                  <div className="flex flex-wrap items-center gap-4 mt-2 text-[13px]">
                    <div>
                      <input
                        aria-label="Reviewer"
                        className="border border-line rounded-md px-2 py-1 text-[13px]"
                        placeholder="Your name"
                        value={reviewer}
                        onChange={(e) => setReviewer(e.target.value)}
                      />
                    </div>
                    <div className="flex items-center gap-2">
                      <label className="flex items-center gap-1">
                        <input type="radio" aria-label="Accept" name="verdict" checked={verdict === "accept"} onChange={() => setVerdict("accept")} />
                        <Check size={13} style={{ color: "var(--ok)" }} /> Accept
                      </label>
                      <label className="flex items-center gap-1">
                        <input type="radio" aria-label="Reject" name="verdict" checked={verdict === "reject"} onChange={() => setVerdict("reject")} />
                        <X size={13} style={{ color: "var(--bad)" }} /> Reject
                      </label>
                    </div>
                  </div>

                  <div className="grid grid-cols-3 gap-4 mt-3">
                    {run?.rubric.map((rub) => (
                      <div key={rub.id} title={rub.question}>
                        <div className="text-[13px] font-medium">{rub.label}</div>
                        <div className="flex gap-1 mt-1">
                          {[1, 2, 3, 4, 5].map((n) => (
                            <label key={n} className="flex items-center text-[12px] tabular-nums">
                              <input
                                type="radio"
                                aria-label={`${rub.label} ${n}`}
                                name={`score-${rub.id}`}
                                checked={scores[rub.id] === n}
                                onChange={() => setScores((s) => ({ ...s, [rub.id]: n }))}
                              />
                              {n}
                            </label>
                          ))}
                        </div>
                        <div className="text-[12px] text-muted mt-1">
                          1: {rub.anchors["1"]}
                        </div>
                        <div className="text-[12px] text-muted">
                          3: {rub.anchors["3"]}
                        </div>
                        <div className="text-[12px] text-muted">
                          5: {rub.anchors["5"]}
                        </div>
                      </div>
                    ))}
                  </div>

                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <select
                      aria-label="Failure mode"
                      className="border border-line rounded-md px-2 py-1 text-[13px]"
                      value={failureMode}
                      onChange={(e) => setFailureMode(e.target.value)}
                    >
                      {run?.taxonomy.map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.label}
                        </option>
                      )) ?? <option value="none">none</option>}
                    </select>
                    {run?.taxonomy
                      .filter((t) => t.id !== "none")
                      .map((t) => (
                        <button
                          key={t.id}
                          title={t.description}
                          className={`chip text-[12px] ${tags.includes(t.id) ? "font-medium" : ""}`}
                          style={tags.includes(t.id) ? { color: "var(--action)" } : undefined}
                          onClick={() => toggleTag(t.id)}
                        >
                          {t.label}
                        </button>
                      ))}
                  </div>

                  <textarea
                    aria-label="Notes"
                    className="border border-line rounded-md px-2 py-1 text-[13px] w-full mt-3"
                    rows={3}
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                  />

                  <div className="flex gap-2 mt-3">
                    <button className="btn btn-primary" disabled={!complete} title={complete ? undefined : "Add your name, a verdict and every score"} onClick={saveReview}>
                      Save review
                    </button>
                    <button className="btn btn-ghost" onClick={askModel}>
                      <Sparkles size={14} /> Ask the model
                    </button>
                  </div>

                  {trial.reviews.length > 0 && (
                    <div className="mt-4">
                      <div className="text-[13px] font-medium">Saved reviews</div>
                      {trial.reviews.map((r) => (
                        <div key={r.id} className="text-[12px] mt-1 flex items-center gap-2">
                          <span style={{ color: verdictColor(r.verdict) }}>{r.verdict}</span>
                          <span className="font-medium">{r.reviewer}</span>
                          <span className="text-muted">({r.source})</span>
                          <span className="text-muted tabular-nums">
                            {r.scores.correctness}/{r.scores.maintainability}/{r.scores.test_quality}
                          </span>
                          {r.failure_mode !== "none" && <span className="chip text-[12px]">{r.failure_mode}</span>}
                          {r.notes && <span className="text-muted">{r.notes}</span>}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function TrajectoryPanel({
  steps,
  openStep,
  setOpenStep,
}: {
  steps: Step[];
  openStep: number | null;
  setOpenStep: (i: number | null) => void;
}) {
  return (
    <div className="surface border border-line rounded-md p-3 overflow-y-auto scroll-thin">
      <h2 className="font-medium text-[13px] mb-2">Trajectory</h2>
      {steps.length === 0 && <Empty>No steps</Empty>}
      <div className="border-l border-line pl-3 flex flex-col gap-2">
        {steps.map((s) => (
          <div key={s.i}>
            <button
              className="text-left w-full text-[13px] flex items-center gap-2"
              style={s.is_error ? { color: "var(--bad)" } : undefined}
              onClick={() => setOpenStep(openStep === s.i ? null : s.i)}
            >
              <span className="chip text-[12px]">{s.kind}</span>
              {s.tool && <span className="font-mono text-[12px]">{s.tool}</span>}
              <span className="truncate">{s.title}</span>
            </button>
            {openStep === s.i && (
              <div className="mt-1">
                {s.input && (
                  <pre className="font-mono text-[12px] whitespace-pre-wrap border border-line rounded-md p-2">{s.input}</pre>
                )}
                {s.output && (
                  <pre className="font-mono text-[12px] whitespace-pre-wrap border border-line rounded-md p-2 mt-1">{s.output}</pre>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function DiffPanel({ title, diff }: { title: string; diff: string }) {
  const lines = useMemo(() => diffLines(diff), [diff]);
  return (
    <div role="region" className="surface border border-line rounded-md p-3 overflow-y-auto scroll-thin" aria-label="Diff">
      <h2 className="font-medium text-[13px] mb-2">{title}</h2>
      {!diff && <Empty>No diff</Empty>}
      <pre className="font-mono text-[12px] whitespace-pre-wrap">
        {lines.map((l, i) => {
          let bg: string | undefined;
          if (l.kind === "add") bg = "color-mix(in srgb, var(--ok) 15%, transparent)";
          else if (l.kind === "del") bg = "color-mix(in srgb, var(--bad) 15%, transparent)";
          return (
            <div
              key={i}
              style={{ background: bg }}
              className={
                l.kind === "file" ? "font-medium" : l.kind === "hunk" ? "text-muted" : undefined
              }
            >
              {l.text || " "}
            </div>
          );
        })}
      </pre>
    </div>
  );
}

function TestsPanel({ trial }: { trial: TrialDetail }) {
  return (
    <div className="surface border border-line rounded-md p-3 overflow-y-auto scroll-thin">
      <h2 className="font-medium text-[13px] mb-2">
        Tests:{" "}
        <span style={{ color: trial.grade.passed ? "var(--ok)" : "var(--bad)" }}>
          {trial.grade.passed ? "passed" : "failed"}
        </span>
      </h2>
      <details className="mb-2">
        <summary className="text-[13px] cursor-pointer">Task prompt</summary>
        <pre className="font-mono text-[12px] whitespace-pre-wrap border border-line rounded-md p-2 mt-1">{trial.prompt}</pre>
      </details>
      {trial.grade.steps.map((s, i) => (
        <details key={i} className="mb-1">
          <summary className="text-[13px] cursor-pointer flex items-center gap-2">
            <span
              className="inline-block w-2 h-2 rounded-full"
              style={{ background: s.passed ? "var(--ok)" : "var(--bad)" }}
            />
            <span className="font-medium">{s.name}</span>
            <span className="text-muted text-[12px]">{s.kind}</span>
            {s.exit != null && <span className="text-muted text-[12px] tabular-nums">exit {s.exit}</span>}
          </summary>
          <pre className="font-mono text-[12px] whitespace-pre-wrap border border-line rounded-md p-2 mt-1">{s.output}</pre>
        </details>
      ))}
    </div>
  );
}

function PreferenceBar({
  disabled,
  onSave,
}: {
  disabled: boolean;
  onSave: (winner: "a" | "b" | "tie", reason: string) => void;
}) {
  const [reason, setReason] = useState("");
  return (
    <div className="mt-3 flex items-center gap-2 surface border border-line rounded-md p-3 text-[13px]">
      <span className="font-medium">Which diff is better?</span>
      <button className="btn btn-ghost" disabled={disabled} onClick={() => onSave("a", reason)}>
        Prefer A
      </button>
      <button className="btn btn-ghost" disabled={disabled} onClick={() => onSave("b", reason)}>
        Prefer B
      </button>
      <button className="btn btn-ghost" disabled={disabled} onClick={() => onSave("tie", reason)}>
        Tie
      </button>
      <input
        aria-label="Preference reason"
        className="border border-line rounded-md px-2 py-1 text-[13px] flex-1"
        placeholder="Why?"
        value={reason}
        onChange={(e) => setReason(e.target.value)}
      />
    </div>
  );
}

export default ReviewPage;
