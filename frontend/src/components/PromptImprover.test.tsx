import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const post = vi.hoisted(() => vi.fn(async (_p: string, _b?: unknown): Promise<any> => ({ task_code: "T-7", task_link: "x" })));
vi.mock("../lib/api", () => ({ post }));

import { PromptImprover, type PromptImproverOutcome, type TaskCardView } from "./PromptImprover";

afterEach(() => { cleanup(); post.mockClear(); });

const outcome = (status: PromptImproverOutcome["status"], reason = ""): PromptImproverOutcome =>
  ({ status, reason, questions_asked: 0, calls: 1, estimated_tokens: 100, item_ids: ["it1"], task_code: null });
const CARD: TaskCardView = {
  goal: "Make jumping feel better", scope: ["Player jump"], quality_ladder_level: "L2",
  acceptance_criteria: [{ id: "AC1", expected: "Apex time is 0.4 s", verification: "playmode_test" }],
  assumptions: ["Keep gravity"], risks: ["Tuning drift"], route: { skills: ["unity-mcp"] },
};

describe("PromptImprover", () => {
  it.each([
    ["proceeded", "Task card ready"], ["asked", "Asked questions"], ["bypassed", "Skipped"],
    ["unavailable", "Prompt improver unavailable"], ["paused", "Paused"],
  ] as const)("renders the %s status", (status, label) => {
    render(<PromptImprover outcome={outcome(status, "because")} sessionId="s1" />);
    expect(screen.getByText(label)).toBeTruthy();
    expect(screen.getByText("because")).toBeTruthy();
    expect(screen.getByRole("note").getAttribute("data-status")).toBe(status);
  });

  it("shows the * hint when bypassed and no Save button without an item", () => {
    render(<PromptImprover outcome={outcome("bypassed")} sessionId="s1" />);
    expect(screen.getByText(/Start a message with \*/)).toBeTruthy();
    expect(screen.queryByText("Save to Tasks")).toBeNull();
  });

  it("previews the task card", () => {
    render(<PromptImprover outcome={outcome("proceeded")} card={CARD} itemId="it1" sessionId="s1" />);
    const card = screen.getByTestId("pi-card").textContent ?? "";
    for (const t of ["Make jumping feel better", "Player jump", "Apex time is 0.4 s", "L2", "Keep gravity", "Tuning drift", "unity-mcp"]) expect(card).toContain(t);
  });

  it("saves to Tasks and shows the task code", async () => {
    const onSaved = vi.fn();
    render(<PromptImprover outcome={outcome("proceeded")} card={CARD} itemId="it1" sessionId="s1" onSaved={onSaved} />);
    await act(async () => { fireEvent.click(screen.getByText("Save to Tasks")); });
    expect(post).toHaveBeenCalledWith("/sessions/s1/prompt-improver/it1/save");
    expect(screen.getByTestId("pi-task-code").textContent).toContain("T-7");
    expect(screen.queryByText("Save to Tasks")).toBeNull();
    expect(onSaved).toHaveBeenCalledWith({ task_code: "T-7", task_link: "x" });
  });

  it("shows the code and a disabled button when already saved, and errors inline", async () => {
    const { unmount } = render(<PromptImprover outcome={outcome("proceeded")} itemId="it1" taskCode="T-3" sessionId="s1" />);
    expect(screen.getByTestId("pi-task-code").textContent).toContain("T-3");
    expect(screen.queryByText("Save to Tasks")).toBeNull();
    unmount();
    post.mockRejectedValueOnce(new Error("nope"));
    render(<PromptImprover outcome={outcome("proceeded")} itemId="it1" sessionId="s1" />);
    await act(async () => { fireEvent.click(screen.getByText("Save to Tasks")); });
    expect(screen.getByRole("alert").textContent).toBe("nope");
    expect((screen.getByText("Save to Tasks") as HTMLButtonElement).disabled).toBe(false);
  });

  it.each(["unavailable", "paused", "bypassed"] as const)("shows no Save button for a %s notice", (status) => {
    render(<PromptImprover outcome={outcome(status, "why")} itemId="it1" sessionId="s1" />);
    expect(screen.getByText("why")).toBeTruthy();
    expect(screen.queryByText("Save to Tasks")).toBeNull();
  });

  it("shows no Save button for a card notice without an item id", () => {
    render(<PromptImprover outcome={outcome("proceeded")} itemId={null} sessionId="s1" />);
    expect(screen.queryByText("Save to Tasks")).toBeNull();
  });

  it("shows a short inline error on a 404 from the save route", async () => {
    post.mockRejectedValueOnce(new Error("404: No such prompt improver card"));
    render(<PromptImprover outcome={outcome("asked")} itemId="it1" sessionId="s1" />);
    await act(async () => { fireEvent.click(screen.getByText("Save to Tasks")); });
    expect(screen.getByRole("alert").textContent).toBe("This card can't be saved to Tasks.");
  });

  it("shows the summary without a card preview when no card is given (old notice)", () => {
    render(<PromptImprover outcome={outcome("proceeded", "older run")} card={null} itemId="old" sessionId="s1" />);
    expect(screen.getByText("older run")).toBeTruthy();
    expect(screen.queryByTestId("pi-card")).toBeNull();
  });
});
