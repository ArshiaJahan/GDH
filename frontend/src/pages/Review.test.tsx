// The Review desk page (drafted by GLM-5.3-Flash, checked and extended by hand).
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  get: vi.fn(async (p: string): Promise<any> => ({})),
  post: vi.fn(async (p: string, b?: any): Promise<any> => ({})),
}));

vi.mock("../lib/api", () => ({ ...api, api: vi.fn() }));
vi.mock("../lib/store", () => ({ actions: { toast: vi.fn() } }));

import { ReviewPage, diffLines, verdictColor } from "./Review";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const RUNS = {
  root: "evals/runs",
  runs: [{ dir: "evals/runs/r1", name: "r1", trials: 2, passed: 1, agents: ["claude_code"], reviews: 0 }],
};

const RUN = {
  dir: "evals/runs/r1",
  rubric: [
    { id: "correctness", label: "Correctness", question: "Does it do what the task asks?", anchors: { "1": "wrong", "3": "mostly", "5": "fully" } },
    { id: "maintainability", label: "Maintainability", question: "q", anchors: { "1": "a", "3": "b", "5": "c" } },
    { id: "test_quality", label: "Test quality", question: "q", anchors: { "1": "a", "3": "b", "5": "c" } },
  ],
  taxonomy: [
    { id: "none", label: "No failure", description: "" },
    { id: "missed_requirement", label: "Missed requirement", description: "" },
  ],
  trials: [
    { key: "t1/claude_code/1", task: "t1", agent: "claude_code", trial: 1, passed: false, blame: "agent", reason: "failed", cost_usd: 1, wall_s: 10, tool_calls: 3, human: null, llm: null },
    { key: "t1/claude_code/2", task: "t1", agent: "claude_code", trial: 2, passed: true, blame: "", reason: "passed", cost_usd: 1, wall_s: 10, tool_calls: 3, human: null, llm: null },
  ],
};

const TRIAL = {
  key: "t1/claude_code/1",
  task: "t1",
  agent: "claude_code",
  trial: 1,
  passed: false,
  blame: "agent",
  reason: "failed",
  prompt: "Fix the clamp",
  diff: "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-old\n+new\n",
  grade: { passed: false, steps: [{ name: "tests", kind: "command", passed: false, exit: 1, output: "AssertionError" }] },
  steps: [
    { i: 0, kind: "system", tool: null, title: "Started on claude-opus-5-5", input: null, output: null, is_error: false, ts: null },
    { i: 1, kind: "tool", tool: "Bash", title: "pytest -q", input: '{"command":"pytest -q"}', output: "1 failed", is_error: true, ts: null },
  ],
  reviews: [],
  preferences: [],
};

api.get.mockImplementation(async (p: string) => {
  if (p.startsWith("/review/runs")) return RUNS;
  if (p.startsWith("/review/run?")) return RUN;
  if (p.startsWith("/review/trial")) return TRIAL;
  if (p.startsWith("/review/agreement")) return { n: 0 };
  return {};
});

const PREREVIEW = {
  id: "r",
  key: TRIAL.key,
  reviewer: "model",
  source: "llm:claude",
  verdict: "reject",
  scores: { correctness: 2, maintainability: 3, test_quality: 3 },
  failure_mode: "missed_requirement",
  tags: [],
  notes: "misses the clamp",
  created_at: 1,
};

api.post.mockImplementation(async (p: string) => {
  if (p === "/review/prereview") return PREREVIEW;
  return {};
});

describe("diffLines", () => {
  it("classifies diff lines", () => {
    const lines = diffLines(TRIAL.diff);
    expect(lines[0]).toMatchObject({ kind: "file" });
    expect(lines.some((l: any) => l.kind === "hunk" && l.text.startsWith("@@"))).toBe(true);
    expect(lines).toContainEqual(expect.objectContaining({ kind: "del", text: "-old" }));
    expect(lines).toContainEqual(expect.objectContaining({ kind: "add", text: "+new" }));
    const kinds = new Set(lines.map((l: any) => l.kind));
    expect(kinds.has("ctx") || kinds.has("file")).toBe(true);
    expect(kinds.has("add")).toBe(true);
    expect(kinds.has("del")).toBe(true);
    expect(kinds.has("hunk")).toBe(true);
  });
});

describe("verdictColor", () => {
  it("maps verdicts to colors", () => {
    expect(verdictColor("accept")).toBeTruthy();
    expect(verdictColor("reject")).toBeTruthy();
    expect(verdictColor(null)).toBeTruthy();
    expect(verdictColor("accept")).not.toBe(verdictColor("reject"));
  });
});

async function openTrial() {
  render(<ReviewPage />);
  const select = await screen.findByRole("combobox", { name: "Run" });
  fireEvent.change(select, { target: { value: RUNS.runs[0].dir } });
  const trialBtn = await screen.findByRole("button", { name: /t1 #1/ });
  fireEvent.click(trialBtn);
  await screen.findByLabelText("Diff");
}

describe("ReviewPage", () => {
  it("renders trial details after selecting run and trial", async () => {
    await openTrial();
    expect(screen.getByText("pytest -q")).toBeTruthy();
    const diff = screen.getByLabelText("Diff");
    expect(within(diff).getByText("+new")).toBeTruthy();
    expect(screen.getByText("AssertionError")).toBeTruthy();
  });

  it("saves a review via the form", async () => {
    await openTrial();
    fireEvent.change(screen.getByLabelText("Reviewer"), { target: { value: "me" } });
    fireEvent.click(screen.getByLabelText("Reject"));
    fireEvent.click(screen.getByLabelText("Correctness 2"));
    fireEvent.change(screen.getByLabelText("Failure mode"), { target: { value: "missed_requirement" } });
    const save = screen.getByRole("button", { name: "Save review" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true); // every rubric score is needed
    fireEvent.click(screen.getByLabelText("Maintainability 4"));
    fireEvent.click(screen.getByLabelText("Test quality 3"));
    expect(save.disabled).toBe(false);
    fireEvent.click(save);
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/review/reviews", expect.objectContaining({ dir: RUN.dir, key: TRIAL.key, verdict: "reject", scores: expect.objectContaining({ correctness: 2 }), failure_mode: "missed_requirement" })));
  });

  it("asks the model for a prereview", async () => {
    await openTrial();
    fireEvent.click(screen.getByRole("button", { name: "Ask the model" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/review/prereview", expect.objectContaining({ key: TRIAL.key })));
    await screen.findByText("Proposed by llm:claude");
    expect((screen.getByLabelText("Notes") as HTMLTextAreaElement).value).toBe("misses the clamp");
  });

  it("keeps the person's name when the model proposes a review", async () => {
    await openTrial();
    fireEvent.change(screen.getByLabelText("Reviewer"), { target: { value: "ali" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask the model" }));
    await screen.findByText("Proposed by llm:claude");
    expect((screen.getByLabelText("Reviewer") as HTMLInputElement).value).toBe("ali");
    fireEvent.click(screen.getByRole("button", { name: "Save review" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/review/reviews", expect.objectContaining({ reviewer: "ali", verdict: "reject" })));
  });

  it("compares two trials of the same task and saves a preference", async () => {
    await openTrial();
    fireEvent.click(screen.getByRole("button", { name: /Compare/ }));
    const pick = screen.getByLabelText("Compare with") as HTMLSelectElement;
    expect(Array.from(pick.options).map((o) => o.value)).toEqual(["", "t1/claude_code/2"]); // not the open trial
    fireEvent.change(pick, { target: { value: "t1/claude_code/2" } });
    fireEvent.change(screen.getByLabelText("Reviewer"), { target: { value: "ali" } });
    fireEvent.change(await screen.findByLabelText("Preference reason"), { target: { value: "B clamps the max" } });
    fireEvent.click(screen.getByRole("button", { name: "Prefer B" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/review/preferences", expect.objectContaining({
      task: "t1", a: "t1/claude_code/1", b: "t1/claude_code/2", winner: "b", reason: "B clamps the max", reviewer: "ali" })));
  });
});
