// The Connectors card lists MCP servers on opening a session (even mid-turn) and again after a turn.
import { act, cleanup, render } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const get = vi.hoisted(() => vi.fn(async (p: string): Promise<unknown> => (p === "/skills" ? { skills: [] } : [])));
vi.mock("../../lib/api", () => ({ get, patch: vi.fn(), post: vi.fn() }));
vi.mock("../../lib/store", () => ({ actions: { go: vi.fn(), toast: vi.fn() } }));
vi.mock("../SidePanel", () => ({ Card: ({ children }: { children: ReactNode }) => <div>{children}</div> }));

import { ConnectorsCard } from "./ConnectorsCard";

afterEach(cleanup);

const session = (id: string, status: string) => ({ id, status, settings: {} }) as any;
const serverFetches = () => get.mock.calls.filter(([p]) => p === "/mcp/servers").length;

describe("ConnectorsCard", () => {
  it("fetches servers per session, running or not, and again when a turn ends", async () => {
    const { rerender } = render(<ConnectorsCard s={session("s1", "running")} />);
    await act(async () => {});
    expect(serverFetches()).toBe(1);
    rerender(<ConnectorsCard s={session("s1", "running")} />);
    await act(async () => {});
    expect(serverFetches()).toBe(1);
    rerender(<ConnectorsCard s={session("s1", "idle")} />); // turn ended
    await act(async () => {});
    expect(serverFetches()).toBe(2);
    rerender(<ConnectorsCard s={session("s2", "running")} />); // another session
    await act(async () => {});
    expect(serverFetches()).toBe(3);
    rerender(<ConnectorsCard s={session("s3", "idle")} />); // switching away from a running one isn't a turn end
    await act(async () => {});
    expect(serverFetches()).toBe(4);
  });
});
