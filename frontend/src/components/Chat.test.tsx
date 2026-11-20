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
import { Chat, formatWait, statusText } from "./Chat";

afterEach(cleanup);

it("reserves readable title space while truncating a long session title", () => {
  const title = "A long title for a Claude subscription session";
  useStore.setState({ currentId: "s1", sessions: [{ id: "s1", title, model: "claude-sonnet-5-5", harness: "claude_code" } as Session] });
  render(<Chat />);
  const heading = screen.getByRole("heading", { name: title });
  expect(heading.classList.contains("truncate")).toBe(true);
  expect(heading.classList.contains("min-w-[6rem]")).toBe(true);
});

it("shows long rate-limit waits in days and hours, not raw seconds", () => {
  expect(formatWait(8)).toBe("8s");
  expect(formatWait(200)).toBe("3m 20s");
  expect(formatWait(7500)).toBe("2h 5m");
  expect(formatWait(546594)).toBe("6d 7h");
  const now = 1_000_000_000_000;
  const retry = { kind: "rate_limit", text: "Claude is busy, retrying in 8s", until: now / 1000 + 8, attempt: 1, max_attempts: 10 };
  expect(statusText(retry, now)).toBe("Rate limited, retrying in 8s");
  const plan = { kind: "rate_limit", text: "Claude plan limit reached (seven day), resets Thu 06:00", until: now / 1000 + 546594 };
  expect(statusText(plan, now)).toBe("Claude plan limit reached (seven day), resets Thu 06:00 (in 6d 7h)");
});
