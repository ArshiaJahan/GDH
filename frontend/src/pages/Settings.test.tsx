// Settings fields that save themselves: numbers only once you're done typing (and when the page
// goes away), and allowlist rules only once they're complete.
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../lib/api", () => ({ api: vi.fn(), del: vi.fn(), get: vi.fn(async () => null), post: vi.fn() }));
vi.mock("../lib/store", () => ({ actions: { toast: vi.fn(), refreshState: vi.fn() }, useStore: (sel: (s: any) => unknown) => sel({ pageArgs: {} }) }));
vi.mock("../components/StorageSettings", () => ({ StorageSettings: () => null }));

import { Allowlist, Num, savableAllowRules, validAllowRule } from "./Settings";

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

const type = (el: HTMLElement, value: string) => fireEvent.change(el, { target: { value } });

describe("Num", () => {
  it("doesn't save half-typed values, only on blur or Enter", () => {
    const onSave = vi.fn();
    render(<Num value={50} onSave={onSave} label="Daily" />);
    const input = screen.getByLabelText("Daily");
    type(input, "5"); // on the way from 50 to 500
    act(() => { vi.advanceTimersByTime(5000); });
    type(input, "500");
    act(() => { vi.advanceTimersByTime(5000); });
    expect(onSave).not.toHaveBeenCalled();
    fireEvent.blur(input);
    expect(onSave).toHaveBeenCalledExactlyOnceWith(500);
    fireEvent.keyDown(input, { key: "Enter" }); // same value: no second save
    expect(onSave).toHaveBeenCalledTimes(1);
  });

  it("saves the typed value when it unmounts (navigating away)", () => {
    const onSave = vi.fn();
    const { unmount } = render(<Num value={4} onSave={onSave} label="Parallel" />);
    type(screen.getByLabelText("Parallel"), "6");
    unmount();
    expect(onSave).toHaveBeenCalledExactlyOnceWith(6);
  });

  it("doesn't save invalid or below-min values", () => {
    const onSave = vi.fn();
    const { unmount } = render(<Num value={4} min={1} onSave={onSave} label="Turns" />);
    const input = screen.getByLabelText("Turns");
    type(input, "");
    fireEvent.blur(input);
    type(input, "0");
    fireEvent.blur(input);
    unmount();
    expect(onSave).not.toHaveBeenCalled();
  });

  it("lets the same value be retried after a failed save", async () => {
    const onSave = vi.fn(async () => false);
    render(<Num value={10} onSave={onSave} label="Job" />);
    const input = screen.getByLabelText("Job");
    type(input, "20");
    fireEvent.blur(input);
    await act(async () => {});
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSave).toHaveBeenCalledTimes(2);
    expect(onSave).toHaveBeenLastCalledWith(20);
  });
});

describe("allowlist rules", () => {
  it("are complete only with a known kind and a non-empty pattern", () => {
    expect(validAllowRule("run_command:git status*")).toBe(true);
    expect(validAllowRule("mcp:github__get_*")).toBe(true);
    expect(validAllowRule("run_command:")).toBe(false);
    expect(validAllowRule("run_command:   ")).toBe(false);
    expect(validAllowRule("run_command")).toBe(false);
    expect(validAllowRule("bogus:x")).toBe(false);
    expect(validAllowRule(":x")).toBe(false);
    expect(savableAllowRules([" edit:* ", "run_command:", "", "delete:tmp/*"])).toEqual(["edit:*", "delete:tmp/*"]);
  });
});

describe("Allowlist", () => {
  it("never saves an incomplete rule, keeps it on screen, and saves it once complete", () => {
    const save = vi.fn();
    const { rerender } = render(<Allowlist rules={["edit:*"]} save={save} />);
    type(screen.getByLabelText("New allowlist rule"), "run_command:");
    fireEvent.click(screen.getByText("Add rule"));
    act(() => { vi.advanceTimersByTime(5000); });
    expect(save).not.toHaveBeenCalled(); // nothing complete changed
    expect((screen.getByLabelText("Allowlist rule 2") as HTMLInputElement).value).toBe("run_command:");
    expect(screen.getByText("Not saved until complete")).toBeTruthy();

    // Another edit saves the complete rules only; the saved list coming back keeps the draft row.
    type(screen.getByLabelText("Allowlist rule 1"), "edit:src/*");
    act(() => { vi.advanceTimersByTime(1000); });
    expect(save).toHaveBeenLastCalledWith(["edit:src/*"]);
    rerender(<Allowlist rules={["edit:src/*"]} save={save} />);
    expect((screen.getByLabelText("Allowlist rule 2") as HTMLInputElement).value).toBe("run_command:");

    type(screen.getByLabelText("Allowlist rule 2"), "run_command:git status*");
    act(() => { vi.advanceTimersByTime(1000); });
    expect(save).toHaveBeenLastCalledWith(["edit:src/*", "run_command:git status*"]);
    expect(screen.queryByText("Not saved until complete")).toBeNull();
  });

  it("keeps an incomplete row when the saved list changes elsewhere", () => {
    const save = vi.fn();
    const { rerender } = render(<Allowlist rules={["edit:*"]} save={save} />);
    type(screen.getByLabelText("New allowlist rule"), "mcp:");
    fireEvent.click(screen.getByText("Add rule"));
    rerender(<Allowlist rules={["edit:*", "delete:tmp/*"]} save={save} />);
    const values = screen.getAllByLabelText(/^Allowlist rule/).map((x) => (x as HTMLInputElement).value);
    expect(values).toEqual(["edit:*", "delete:tmp/*", "mcp:"]);
    expect(save).not.toHaveBeenCalled();
  });
});
