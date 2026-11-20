import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

vi.mock("./Composer", () => ({ Composer: () => null }));
vi.mock("./ClaudeCode", () => ({ ClaudeCodeChip: () => null, ClaudeLoginNotice: () => null }));
vi.mock("./NewSession", () => ({ NewSession: () => null }));
vi.mock("./SessionTasks", () => ({ SessionTasks: () => null }));
vi.mock("./SetupChecklist", () => ({ SetupChecklist: () => null, NoKeyNotice: () => null }));
vi.mock("./LimitsBanner", () => ({ SessionLimitBanner: () => null }));
vi.mock("./toolRenderers", () => ({ toolRenderers: {} }));
vi.mock("./ui", () => ({ useModelCatalog: () => {}, modelLabel: (m: string) => m, ProviderDot: () => null, EffortMeter: () => null }));

import { useStore, type Session } from "../lib/store";
import { Chat } from "./Chat";

afterEach(cleanup);

it("reserves readable title space while truncating a long session title", () => {
  const title = "A long title for a Claude subscription session";
  useStore.setState({ currentId: "s1", sessions: [{ id: "s1", title, model: "claude-sonnet-5-5", harness: "claude_code" } as Session] });
  render(<Chat />);
  const heading = screen.getByRole("heading", { name: title });
  expect(heading.classList.contains("truncate")).toBe(true);
  expect(heading.classList.contains("min-w-[6rem]")).toBe(true);
});
