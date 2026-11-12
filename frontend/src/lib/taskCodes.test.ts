import { describe, expect, it } from "vitest";
import { formatCode, initials, normalizeCode, parseCode, parseTaskCommand, splitTaskCodes, taskPick, taskSuggestions } from "./taskCodes";

describe("task codes", () => {
  it("parses every reference form, case-insensitively", () => {
    for (const ref of ["Task00001", "task00001", "TASK00001", "task1", "1", "00001", "#1", "#Task00001", " Task-1 "]) expect(parseCode(ref)).toBe(1);
    expect(parseCode("Task123456")).toBe(123456);
    expect(parseCode(42)).toBe(42);
    for (const bad of ["", "0", "Task00000", "Task", "abc", "Task1x", "1.5", null, undefined, -1]) expect(parseCode(bad as any)).toBeNull();
  });

  it("formats with five digits and grows past them", () => {
    expect(formatCode(7)).toBe("Task00007");
    expect(formatCode(123456)).toBe("Task123456");
    expect(normalizeCode("#12")).toBe("Task00012");
    expect(normalizeCode("nope")).toBeNull();
  });

  it("finds codes in text for chips, not inside longer words", () => {
    expect(splitTaskCodes("Fix Task00012 and task00003.")).toEqual(["Fix ", { code: "Task00012", raw: "Task00012" }, " and ", { code: "Task00003", raw: "task00003" }, "."]);
    expect(splitTaskCodes("MyTask00001 Task12 Task00001x")).toEqual(["MyTask00001 Task12 Task00001x"]);
    expect(splitTaskCodes("Task00000")).toEqual(["Task00000"]);
    expect(splitTaskCodes("")).toEqual([""]);
  });

  it("initials", () => {
    expect(initials("me")).toBe("Me");
    expect(initials("agent")).toBe("AI");
    expect(initials("Ana Ruiz")).toBe("AR");
    expect(initials("sam")).toBe("SA");
  });
});

describe("/task command parsing", () => {
  it("new with labels, priority and column", () => {
    expect(parseTaskCommand("/task new Fix the jump buffer #player #input !high @in-progress")).toEqual(
      { kind: "new", title: "Fix the jump buffer", labels: ["player", "input"], priority: "high", column: "in progress" });
    expect(parseTaskCommand("/task new Wow!   !nope")).toEqual({ kind: "new", title: "Wow! !nope", labels: [] });
    expect(parseTaskCommand("/task new #only-a-label").kind).toBe("error");
  });

  it("open, move, done, list, link", () => {
    expect(parseTaskCommand("/task")).toEqual({ kind: "board" });
    expect(parseTaskCommand("/task task12")).toEqual({ kind: "open", code: "Task00012" });
    expect(parseTaskCommand("/task #3")).toEqual({ kind: "open", code: "Task00003" });
    expect(parseTaskCommand("/task move 3 In progress")).toEqual({ kind: "move", code: "Task00003", column: "In progress" });
    expect(parseTaskCommand("/task done Task00004")).toEqual({ kind: "done", code: "Task00004" });
    expect(parseTaskCommand("/task link 00005")).toEqual({ kind: "link", code: "Task00005" });
    expect(parseTaskCommand("/task list jump bug")).toEqual({ kind: "list", query: "jump bug" });
    expect(parseTaskCommand("/task list")).toEqual({ kind: "list", query: "" });
    for (const bad of ["/task move 3", "/task move x Done", "/task done", "/task link nope", "/task frobnicate", "/task 3 extra"]) {
      expect(parseTaskCommand(bad).kind).toBe("error");
    }
  });

  it("suggests subcommands, codes and columns", () => {
    const hits = [{ code: "Task00012", title: "Jump" }, { code: "Task00011", title: "Run" }];
    const cols = ["Backlog", "To do", "In progress", "Done"];
    expect(taskSuggestions("/task m", hits, cols).map((s) => s.value)).toEqual(["/task move ", "/task Task00012", "/task Task00011"]);
    expect(taskSuggestions("/task ", hits, cols)[0].value).toBe("/task new ");
    expect(taskSuggestions("/task move Ta", hits, cols).map((s) => s.value)).toEqual(["/task move Task00012 ", "/task move Task00011 "]);
    expect(taskSuggestions("/task done 1", hits, cols)[0].value).toBe("/task done Task00012");
    expect(taskSuggestions("/task move Task00012 pro", hits, cols).map((s) => s.value)).toEqual(["/task move Task00012 In progress"]);
    expect(taskSuggestions("/task new Something", hits, cols)).toEqual([]);
    expect(taskSuggestions("/model x", hits, cols)).toEqual([]);
  });

  it("Enter takes a suggestion only while a code or column is half-typed", () => {
    const cols = ["In progress"];
    expect(taskPick("/task Ta", cols)).toBe(true);
    expect(taskPick("/task Task00012", cols)).toBe(false);
    expect(taskPick("/task list", cols)).toBe(false);
    expect(taskPick("/task mo", cols)).toBe(true);
    expect(taskPick("/task move ta", cols)).toBe(true);
    expect(taskPick("/task move 12", cols)).toBe(false);
    expect(taskPick("/task move 12 in", cols)).toBe(true);
    expect(taskPick("/task move 12 in progress", cols)).toBe(false);
    expect(taskPick("/task new Fix it", cols)).toBe(false);
  });
});
