import { describe, expect, it } from "vitest";
import { campaignNotice, describeCondition, listItems, parseWorkflowCommand, phaseChecks, phaseLabel, spendLabel, statusTone, templatesFor, wordCount } from "./campaigns";

describe("campaign helpers", () => {
  it("labels phases and statuses", () => {
    const phases = [{ name: "Spec", type: "plan", skills: [], done_when: [] }, { name: "Build", type: "build", skills: [], done_when: [] }];
    expect(phaseLabel({ phase: 1, phases, status: "running" })).toBe("2/2 Build");
    expect(phaseLabel({ phase: -1, phases, status: "planning" })).toBe("plan");
    expect(phaseLabel({ phase: -1, phases, status: "done" })).toBe("2/2");
    expect(statusTone("parked")).toBe("bad");
    expect(statusTone("waiting_user")).toBe("warn");
    expect(statusTone("running")).toBe("action");
    expect(statusTone("done")).toBe("ok");
  });

  it("describes done_when conditions like the backend", () => {
    expect(describeCondition({ type: "file_exists", path: "docs/specs/*.md", newer_than: "phase_start" })).toBe("file docs/specs/*.md (new this phase)");
    expect(describeCondition({ type: "gate", level: "L2", expect: "fail" })).toBe("gate L2 (a failing repro test)");
    expect(describeCondition({ type: "gate", level: "story", stories: "milestone" })).toBe("gate stories done (milestone stories)");
    expect(describeCondition({ type: "git_clean", paths: ["Assets"] })).toBe("git clean: Assets");
    expect(describeCondition({ type: "command_passes", observe: "backlog_lint" })).toBe("backlog_lint passes");
  });

  it("merges the last results into the phase checks", () => {
    const p = { name: "B", type: "build", skills: [], done_when: [{ type: "gate" as const, level: "L1" }, { type: "git_clean" as const }],
      results: [{ index: 0, type: "gate" as const, label: "gate L1", status: "fail" as const, detail: "2 errors" }] };
    expect(phaseChecks(p)).toEqual([{ label: "gate L1", status: "fail", detail: "2 errors" }, { label: "git clean", status: "pending", detail: "" }]);
  });

  it("parses /workflow and counts words", () => {
    expect(parseWorkflowCommand("/workflow bugfix the jump double-fires")).toEqual({ id: "bugfix", request: "the jump double-fires" });
    expect(parseWorkflowCommand("/workflow")).toEqual({ id: "", request: "" });
    expect(parseWorkflowCommand("/skill x")).toBeNull();
    expect(wordCount("  a b  c ")).toBe(3);
    expect(spendLabel(1.2, 10)).toBe("$1.20 / $10");
    expect(listItems("<!-- c -->\n- one\n* two\ntext")).toEqual(["one", "two"]);
    const t = (id: string, kinds: ("chain" | "campaign")[]) => ({ id, kinds } as any);
    expect(templatesFor([t("a", ["chain"]), t("b", ["campaign"])], "campaign").map((x) => x.id)).toEqual(["b"]);
  });

  it("words the app-wide campaign notices and skips the user's own actions", () => {
    expect(campaignNotice("campaign.done", { id: "c1", title: "Boss Rush" })).toEqual({ text: "Boss Rush is done.", kind: "info", id: "c1" });
    expect(campaignNotice("campaign.paused", { id: "c1", title: "Boss Rush", status: "parked", reason: "budget reached" }))
      .toEqual({ text: "Boss Rush is parked and needs you: budget reached", kind: "error", id: "c1" });
    expect(campaignNotice("campaign.paused", { id: "c1", title: "B", status: "waiting_user", reason: "the agent asked you a question" })?.text)
      .toBe("B is waiting for you: the agent asked you a question");
    expect(campaignNotice("campaign.paused", { id: "c1", title: "B", status: "paused", reason: "phase 2 is ready in a new session" })?.text)
      .toBe("B paused: phase 2 is ready in a new session");
    expect(campaignNotice("campaign.paused", { id: "c1", title: "B", status: "paused", reason: "paused by you" })).toBeNull();
    expect(campaignNotice("campaign.paused", { id: "c1", title: "B", status: "interrupted", reason: "the app closed" })).toBeNull();
    expect(campaignNotice("campaign.updated", { id: "c1", status: "running" })).toBeNull();
  });
});
