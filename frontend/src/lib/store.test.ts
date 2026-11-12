// Long sessions open on their newest page and load older ones on demand; a stream too far
// behind to replay (ws.resync) reloads state over REST.
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.hoisted(() => vi.fn(async (_path: string): Promise<any> => null));
vi.mock("./api", () => ({ get, post: vi.fn(async () => ({})) }));

import { actions, handleEvent, useStore } from "./store";

const msg = (i: number) => ({ id: `m${i}`, role: "user", content: [{ type: "text", text: `t${i}` }], meta: {} });
const range = (a: number, b: number) => Array.from({ length: b - a }, (_, i) => msg(a + i));

beforeEach(() => {
  get.mockReset();
  useStore.setState({ messages: {}, paging: {}, currentId: null, sessions: [] });
});

describe("message paging", () => {
  it("opens on the newest page and prepends older pages", async () => {
    get.mockImplementation(async (p: string) => {
      if (p.startsWith("/sessions/s1/messages/page")) {
        return p.includes("before=m5") ? { messages: range(0, 5), has_more: false, compacted: 2 }
          : { messages: range(5, 10), has_more: true, compacted: 2 };
      }
      return [];
    });
    await actions.openSession("s1");
    expect(useStore.getState().messages.s1.map((m) => m.id)).toEqual(["m5", "m6", "m7", "m8", "m9"]);
    expect(useStore.getState().paging.s1).toMatchObject({ hasMore: true, compacted: 2, showCompacted: false });
    expect(await actions.loadOlder("s1")).toBe(true);
    expect(useStore.getState().messages.s1.map((m) => m.id)).toEqual(range(0, 10).map((m) => m.id));
    expect(useStore.getState().paging.s1.hasMore).toBe(false);
    expect(await actions.loadOlder("s1")).toBe(false); // nothing more: no request
    expect(get.mock.calls.filter(([p]) => p.includes("before=")).length).toBe(1);
  });

  it("asks for compacted messages only when shown", async () => {
    get.mockImplementation(async () => ({ messages: range(0, 3), has_more: false, compacted: 0 }));
    useStore.setState({ messages: { s1: range(1, 3) as any } });
    await actions.showCompacted("s1");
    expect(get.mock.calls.at(-1)?.[0]).toContain("compacted=1");
    expect(useStore.getState().paging.s1.showCompacted).toBe(true);
  });
});

describe("reloadMessages", () => {
  it("keeps messages that arrived live while the page loaded", async () => {
    useStore.setState({ messages: { s1: range(0, 3) as any } });
    get.mockImplementation(async () => {
      handleEvent({ type: "message.created", session_id: "s1", data: { message: msg(3) }, ts: 0, seq: 1 }); // arrives mid-request
      return { messages: range(0, 3), has_more: false, compacted: 0 };
    });
    await actions.reloadMessages("s1");
    expect(useStore.getState().messages.s1.map((m) => m.id)).toEqual(["m0", "m1", "m2", "m3"]);
  });
});

describe("ws.resync", () => {
  it("reloads sessions and the open chat, and drops other cached chats", async () => {
    useStore.setState({ currentId: "s1", messages: { s1: range(0, 1) as any, s2: range(0, 1) as any }, streaming: { s1: { id: "x", text: "partial", thinking: "", tools: [] } } });
    get.mockImplementation(async (p: string) => {
      if (p === "/state") return { last_seq: 99 };
      if (p.startsWith("/sessions?view=all")) return [{ id: "s1" }];
      if (p.startsWith("/sessions/s1/messages/page")) return { messages: range(0, 4), has_more: false, compacted: 0 };
      if (p === "/limits") return { global: null, sessions: {} };
      return [];
    });
    handleEvent({ type: "ws.resync", session_id: null, data: {}, ts: 0, seq: 99 });
    await vi.waitFor(() => expect(useStore.getState().messages.s1?.length).toBe(4));
    expect(useStore.getState().messages.s2).toBeUndefined();
    expect(useStore.getState().streaming.s1).toBeUndefined();
  });

  it("opens the next live session when the open one was deleted meanwhile, or the empty state", async () => {
    useStore.setState({ currentId: "gone", page: "chat", messages: { gone: range(0, 1) as any } });
    get.mockImplementation(async (p: string) => {
      if (p === "/state") return { last_seq: 5 };
      if (p.startsWith("/sessions?view=all")) return [{ id: "gone", deleted: true }, { id: "old", archived: true }, { id: "s2" }];
      if (p.startsWith("/sessions/s2/messages/page")) return { messages: range(0, 2), has_more: false, compacted: 0 };
      if (p === "/limits") return { global: null, sessions: {} };
      return [];
    });
    await actions.resync();
    expect(useStore.getState().currentId).toBe("s2");
    expect(useStore.getState().messages.s2?.length).toBe(2);

    useStore.setState({ currentId: "s2", page: "settings" });
    get.mockImplementation(async (p: string) => {
      if (p === "/state") return { last_seq: 6 };
      if (p === "/limits") return { global: null, sessions: {} };
      return [];
    });
    await actions.resync();
    expect(useStore.getState().currentId).toBeNull();
    expect(useStore.getState().page).toBe("settings");
  });
});
