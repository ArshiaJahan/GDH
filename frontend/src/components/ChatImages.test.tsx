import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("./Composer", () => ({ Composer: () => null }));
vi.mock("./ClaudeCode", () => ({ ClaudeCodeChip: () => null, ClaudeLoginNotice: () => null }));
vi.mock("./NewSession", () => ({ NewSession: () => null }));
vi.mock("./SessionTasks", () => ({ SessionTasks: () => null }));
vi.mock("./SetupChecklist", () => ({ SetupChecklist: () => null, NoKeyNotice: () => null }));
vi.mock("./LimitsBanner", () => ({ SessionLimitBanner: () => null }));
vi.mock("./toolRenderers", () => ({ toolRenderers: {} }));
vi.mock("./ui", () => ({ useModelCatalog: () => {}, modelLabel: (m: string) => m, ProviderDot: () => null, EffortMeter: () => null }));

import { connect } from "../lib/api";
import { useStore, type Msg, type Session } from "../lib/store";
import { Chat } from "./Chat";

const img = (path: string, name: string) => ({ type: "image", path, name, media_type: "image/png" });
const use = (id: string, prompt?: string) => ({ type: "tool_use", id, name: "comfyplug", input: { action: "image", prompt } });
const result = (id: string, ...imgs: any[]) => ({ type: "tool_result", tool_use_id: id, content: [{ type: "text", text: "ok" }, ...imgs] });
const asst = (id: string, ...content: any[]): Msg => ({ id, role: "assistant", content, meta: {} });
const toolRes = (id: string, ...content: any[]): Msg => ({ id, role: "user", content, meta: { tool_results: true } });
const user = (id: string, text: string): Msg => ({ id, role: "user", content: [{ type: "text", text }], meta: {} });

function load(messages: Msg[]) {
  useStore.setState({ currentId: "s1", sessions: [{ id: "s1", title: "t", model: "m", harness: "agent_sdk", status: "idle" } as Session], messages: { s1: messages }, toolRuns: {} });
}

beforeEach(async () => { sessionStorage.setItem("ws-token", "tok"); await connect(); });
afterEach(cleanup);

it("shows a tool result's images inline at the call, lazy, with the prompt as alt text", () => {
  load([user("u1", "draw"), asst("a1", { type: "text", text: "Here" }, use("t1", "a red fox")), toolRes("r1", result("t1", img("/d/fox.png", "fox.png")))]);
  render(<Chat />);
  const inline = screen.getByTestId("inline-images");
  const im = within(inline).getByAltText("a red fox") as HTMLImageElement;
  expect(im.getAttribute("loading")).toBe("lazy");
  expect(im.src).toContain("/api/file");
  expect(decodeURIComponent(im.src)).toContain("/d/fox.png");
});

it("adds an end-of-turn strip with every image of the turn in order, and none for a turn without images", () => {
  load([
    user("u1", "one"), asst("a1", use("t1", "first"), use("t2", "second")), toolRes("r1", result("t1", img("/d/1.png", "1.png")), result("t2", img("/d/2.png", "2.png"), img("/d/3.png", "3.png"))),
    asst("a2", { type: "text", text: "all finished" }),
    user("u2", "two"), asst("a3", { type: "text", text: "plain reply" }),
  ]);
  render(<Chat />);
  const strips = screen.getAllByTestId("turn-strip");
  expect(strips).toHaveLength(1);
  const buttons = within(strips[0]).getAllByRole("button");
  expect(buttons.map((b) => b.getAttribute("aria-label"))).toEqual([
    "Open image 1 of 3: first", "Open image 2 of 3: second", "Open image 3 of 3: second"]);
  // The strip sits at the end of the turn: after the last assistant message ("all finished"), not after the first.
  const done = screen.getByText("all finished");
  expect(done.compareDocumentPosition(strips[0]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

it("opens the lightbox on the clicked strip thumbnail, steps with the arrows and closes on Escape", () => {
  load([user("u1", "x"), asst("a1", use("t1", "first")), toolRes("r1", result("t1", img("/d/1.png", "1.png"), img("/d/2.png", "2.png")))]);
  render(<Chat />);
  fireEvent.click(within(screen.getByTestId("turn-strip")).getByRole("button", { name: /image 2 of 2/ }));
  const dlg = screen.getByRole("dialog");
  expect(within(dlg).getByText("2.png", { selector: "span" })).toBeTruthy();
  expect(within(dlg).getByText("2 / 2")).toBeTruthy();
  fireEvent.keyDown(window, { key: "ArrowLeft" });
  expect(within(screen.getByRole("dialog")).getByText("1.png", { selector: "span" })).toBeTruthy();
  fireEvent.keyDown(window, { key: "Escape" });
  expect(screen.queryByRole("dialog")).toBeNull();
});

it("opens the same lightbox from the inline image", () => {
  load([user("u1", "x"), asst("a1", use("t1", "fox")), toolRes("r1", result("t1", img("/d/1.png", "1.png")))]);
  render(<Chat />);
  fireEvent.click(within(screen.getByTestId("inline-images")).getByRole("button"));
  expect(within(screen.getByRole("dialog")).getByText("1.png", { selector: "span" })).toBeTruthy();
});
