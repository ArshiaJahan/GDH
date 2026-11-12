import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { SkillLoadRow } from "./SkillLoadRow";

afterEach(cleanup);

it("starts collapsed and shows the skill protocol on demand", () => {
  const m = { id: "load", role: "user" as const, meta: { skill_load: "play-verify" },
    content: [{ type: "text", text: "<skill>Full verification protocol</skill>" }] };
  render(<SkillLoadRow m={m} />);
  const chip = screen.getByRole("button", { name: "Skill loaded: play-verify · show" });
  expect(chip.getAttribute("aria-expanded")).toBe("false");
  expect(screen.queryByText(m.content[0].text)).toBeNull();
  fireEvent.click(chip);
  expect(screen.getByText(m.content[0].text)).toBeTruthy();
  const hide = screen.getByRole("button", { name: "Skill loaded: play-verify · hide" });
  expect(hide.getAttribute("aria-expanded")).toBe("true");
  fireEvent.click(hide);
  expect(screen.queryByText(m.content[0].text)).toBeNull();
});
