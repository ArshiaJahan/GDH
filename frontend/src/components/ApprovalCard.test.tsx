// Approval kinds without their own renderer use the generic card (subject, markdown, buttons, note),
// and harness-written chat messages are dispatched to their row components by meta key.
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const post = vi.hoisted(() => vi.fn(async () => ({})));
vi.mock("../lib/api", () => ({ post }));

import { ApprovalCard } from "./ApprovalCard";
import { metaRow } from "./rows";
import { GateRow } from "./rows/GateRow";
import { SkillLoadRow } from "./rows/SkillLoadRow";

afterEach(() => { cleanup(); post.mockClear(); });

describe("generic approval card", () => {
  it("shows subject and markdown, and answers with the chosen button and the note", async () => {
    render(<ApprovalCard a={{ id: "apr_1", kind: "gate_escalation", status: "pending", session_id: "s", payload: {
      subject: "Gate still fails", markdown: "**3 errors** in Hit.cs", note: { label: "Your notes" },
      buttons: [{ id: "accept", label: "Accept as is", decision: "approve", style: "primary" }, { id: "park", label: "Park", decision: "deny" }],
    } }} />);
    expect(screen.getByText("Gate still fails")).toBeTruthy();
    expect(screen.getByText("3 errors").tagName).toBe("STRONG");
    expect(screen.queryByText("Approve")).toBeNull();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "try later" } });
    await act(async () => { fireEvent.click(screen.getByText("Park")); });
    expect(post).toHaveBeenCalledWith("/approvals/apr_1", { decision: "deny", choice: "park", note: "try later" });
  });

  it("falls back to Approve / Decline without buttons", async () => {
    render(<ApprovalCard a={{ id: "apr_2", kind: "hook_trust", status: "pending", session_id: "s", payload: { subject: ".gamedevworkstation/hooks.toml", markdown: "x" } }} />);
    expect(screen.getByText("Trust this hook file?")).toBeTruthy();
    await act(async () => { fireEvent.click(screen.getByText("Approve")); });
    expect(post).toHaveBeenCalledWith("/approvals/apr_2", { decision: "approve", choice: undefined, note: undefined });
  });

  it("keeps the dedicated renderers' answer unchanged", async () => {
    render(<ApprovalCard a={{ id: "apr_3", kind: "command", status: "pending", session_id: "s", payload: { command: "ls", cwd: "/tmp" } }} />);
    await act(async () => { fireEvent.click(screen.getByText("Approve")); });
    expect(post).toHaveBeenCalledWith("/approvals/apr_3", { decision: "approve" });
  });
});

describe("chat meta rows", () => {
  const msg = (meta: Record<string, unknown>) => ({ id: "m", role: "user" as const, content: [{ type: "text", text: "body" }], meta });
  it("dispatches by meta key", () => {
    expect(metaRow(msg({ gate: { id: "unity.compile", status: "fail", attempt: 1, max: 2 } }))).toBe(GateRow);
    expect(metaRow(msg({ skill_load: "play-verify" }))).toBe(SkillLoadRow);
    expect(metaRow(msg({ invoked_skill: "x" }))).toBeNull();
    render(<GateRow m={msg({ gate: { id: "unity.compile", status: "fail", attempt: 1, max: 2 } })} />);
    expect(screen.getByText("Gate unity.compile failed (attempt 1/2)")).toBeTruthy();
  });
});
