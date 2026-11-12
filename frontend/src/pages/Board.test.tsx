// The Tasks page: columns with cards (code, priority, labels, due, assignees, subtasks, agent
// badge), the filter bar's search query, and the task drawer.
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const col = (id: string, name: string, count: number, is_done = false) => ({ id, board_id: "brd_game", name, sort_order: 0, is_done, count });
const BOARDS = { boards: [{ id: "brd_game", name: "Game", sort_order: 0, columns: [col("c1", "Backlog", 1), col("c2", "To do", 0), col("c3", "In progress", 1), col("c4", "Review", 0), col("c5", "Done", 0, true)] }],
  people: ["me", "agent", "Ana Ruiz"] };
const task = (o: Record<string, unknown>) => ({
  id: "tk_1", code: "Task00001", num: 1, title: "Jump buffer", board_id: "brd_game", board: "Game", column_id: "c1", column: "Backlog", done: false,
  position: 0, priority: "none", labels: [], due: null, overdue: false, assignees: [], agent_touched: false, created_by: "me",
  subtasks: { done: 0, total: 0 }, comments: 0, sessions: 0, archived: false, archived_at: null, created_at: 1, updated_at: 1, ...o,
});
const TASKS = [
  task({}),
  task({ id: "tk_2", code: "Task00002", num: 2, title: "Boss arena", column_id: "c3", column: "In progress", priority: "urgent", labels: ["level"],
    due: "2020-01-02", overdue: true, assignees: ["me", "agent", "Ana Ruiz"], agent_touched: true, subtasks: { done: 1, total: 3 }, comments: 2 }),
];
const DETAIL = { ...TASKS[1], description: "Build the **arena**", subtasks_list: [{ id: "st_1", title: "Greybox", done: true, items: [{ id: "ci_1", title: "Walls", done: false }] }],
  comments_list: [{ id: "cm_1", author: "agent", by_agent: true, body: "Started Task00001 too", session_id: null, created_at: 1 }],
  activity: [{ actor: "agent", action: "moved", text: "moved from To do to In progress", session_id: null, ts: 1 }], linked_sessions: [] };

const api = vi.hoisted(() => ({
  get: vi.fn(async (p: string): Promise<any> => {
    if (p === "/tasks/boards") return BOARDS;
    if (p.startsWith("/tasks/search")) return { tasks: TASKS, total: 2 };
    if (p === "/tasks/archived") return { tasks: [], total: 0 };
    if (p.startsWith("/tasks/items/")) return DETAIL;
    return {};
  }),
  post: vi.fn(async (p: string): Promise<any> => (p.startsWith("/tasks/items/") ? DETAIL : {})), patch: vi.fn(async () => DETAIL), del: vi.fn(async () => ({})),
}));
vi.mock("../lib/api", () => ({ ...api, api: vi.fn() }));

import { BoardPage, searchQuery } from "./Board";

afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("BoardPage", () => {
  it("renders the columns and the cards", async () => {
    render(<BoardPage />);
    const progress = await screen.findByRole("region", { name: "Column In progress" });
    expect(screen.getAllByRole("region").map((r) => r.getAttribute("data-column"))).toEqual(["Backlog", "To do", "In progress", "Review", "Done"]);
    expect(screen.getByLabelText("Done column")).toBeTruthy();
    const card = await within(progress).findByRole("button", { name: "Task00002: Boss arena" });
    expect(within(card).getByText("Task00002")).toBeTruthy();
    expect(within(card).getByText("urgent")).toBeTruthy();
    expect(within(card).getByText("#level")).toBeTruthy();
    expect(card.querySelector("[data-overdue]")?.className).toContain("text-bad");
    expect(within(card).getByText("1/3")).toBeTruthy();
    expect(within(card).getByLabelText("Agent touched")).toBeTruthy();
    expect(within(card).getByLabelText("Assigned to You").textContent).toBe("Me");
    expect(within(card).getByLabelText("Assigned to Ana Ruiz").textContent).toBe("AR");
    expect(within(card).getByLabelText("Assigned to Agent")).toBeTruthy();
    const backlog = screen.getByRole("region", { name: "Column Backlog" });
    expect(within(backlog).getByRole("button", { name: "Task00001: Jump buffer" }).querySelector("[data-overdue]")).toBeNull();
    expect(within(screen.getByRole("region", { name: "Column Review" })).getByText("No tasks")).toBeTruthy();
    expect(api.get).toHaveBeenCalledWith(searchQuery("brd_game", { q: "", assignee: "", label: "", priority: "", due: "" }));
  });

  it("opens the drawer with every section", async () => {
    render(<BoardPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Task00002: Boss arena" }));
    const drawer = await screen.findByRole("dialog", { name: "Task00002: Boss arena" });
    expect(within(drawer).getByLabelText("Title")).toHaveProperty("value", "Boss arena");
    expect(within(drawer).getByText("Overdue")).toBeTruthy();
    expect(within(drawer).getByText("Greybox")).toBeTruthy();
    expect(within(drawer).getByText("Walls")).toBeTruthy();
    expect(within(drawer).getByText("arena").tagName).toBe("STRONG");
    expect(within(drawer).getByRole("button", { name: "Open task Task00001" })).toBeTruthy(); // a code in a comment is a chip
    fireEvent.click(within(drawer).getByLabelText("Done: Greybox"));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/tasks/items/Task00002/subtasks", { ops: [{ op: "toggle", id: "st_1", done: false }] }));
    fireEvent.change(within(drawer).getByLabelText("Priority"), { target: { value: "low" } });
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith("/tasks/items/Task00002", { priority: "low" }));
    act(() => { fireEvent.click(within(drawer).getByRole("button", { name: "Close" })); });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("builds the search query from the filters", () => {
    const q = new URLSearchParams(searchQuery("b1", { q: " jump ", assignee: "me", label: "", priority: "high", due: "overdue" }).split("?")[1]);
    expect(Object.fromEntries(q)).toEqual({ board: "b1", include_done: "true", limit: "2000", q: "jump", assignee: "me", priority: "high", due: "overdue" });
  });
});
