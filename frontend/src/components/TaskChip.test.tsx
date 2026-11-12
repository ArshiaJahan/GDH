// Task codes in chat text render as chips that open the task on the Tasks page.
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../lib/api", () => ({ api: vi.fn(), get: vi.fn(async () => ({})), post: vi.fn(), patch: vi.fn(), del: vi.fn() }));

import { MdLite } from "../lib/mdlite";
import { useStore } from "../lib/store";
import { SafeMarkdown } from "./SafeMarkdown";
import { TaskContextRow } from "./rows/TaskContextRow";
import { metaRow } from "./rows";

afterEach(cleanup);

const chips = (root: HTMLElement) => [...root.querySelectorAll("[data-task-chip]")].map((el) => el.getAttribute("data-task-chip"));

describe("task chips", () => {
  it("in user text (MdLite), not inside inline code", () => {
    const { container } = render(<MdLite text={"Please look at task00012 and **Task00003**; `Task00004` stays code. Task12 isn't one."} />);
    expect(chips(container)).toEqual(["Task00012", "Task00003"]);
    expect(container.textContent).toContain("Please look at task00012 and Task00003");
    expect(container.querySelector("code")?.textContent).toBe("Task00004");
  });

  it("in agent Markdown (SafeMarkdown), not inside code or links", () => {
    const { container } = render(<SafeMarkdown text={"Done: **Task00007**, see `Task00008` and [Task00009](https://example.com).\n\n```\nTask00010\n```"} />);
    expect(chips(container)).toEqual(["Task00007"]);
    expect(container.querySelector("a[href='https://example.com']")).toBeTruthy();
  });

  it("opens the task on the Tasks page", () => {
    render(<MdLite text="see Task00042" />);
    fireEvent.click(screen.getByRole("button", { name: "Open task Task00042" }));
    expect(useStore.getState().page).toBe("board");
    expect(useStore.getState().pageArgs).toEqual({ task: "Task00042" });
  });

  it("an attached task is a collapsed row", () => {
    const m = { id: "m", role: "user" as const, meta: { task_context: "Task00005" }, content: [{ type: "text", text: "Task00005: Main menu\nDescription…" }] };
    expect(metaRow(m)).toBe(TaskContextRow);
    render(<TaskContextRow m={m} />);
    expect(screen.getByRole("note", { name: "Task attached: Task00005" })).toBeTruthy();
    expect(screen.queryByText(/Description…/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "· show" }));
    expect(screen.getByText(/Description…/)).toBeTruthy();
  });
});
