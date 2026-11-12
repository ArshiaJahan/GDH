import { describe, expect, it } from "vitest";
import { validateSkill } from "./skillValidate";

const md = (fm: string, body = "\n# Do it\n\nSteps.\n") => `---\n${fm}\n---\n${body}`;
const errors = (r: ReturnType<typeof validateSkill>) => r.issues.filter((i) => i.severity === "error");

describe("validateSkill", () => {
  it("accepts a valid skill and returns its name and description", () => {
    const r = validateSkill(md("name: notes\ndescription: Turn notes into action items."), { folder: "notes" });
    expect(r.issues).toEqual([]);
    expect(r.name).toBe("notes");
    expect(r.description).toBe("Turn notes into action items.");
  });

  it("accepts folded and quoted descriptions", () => {
    const r = validateSkill(md('name: notes\ndescription: >\n  Turn notes into\n  action items.\nargument-hint: "[file]"'), { folder: "notes" });
    expect(r.issues).toEqual([]);
    expect(r.description).toBe("Turn notes into action items.\n");
  });

  it("flags missing frontmatter and an unclosed block", () => {
    expect(errors(validateSkill("# Just a title\n"))[0].message).toMatch(/start with frontmatter/);
    expect(errors(validateSkill("---\nname: x\ndescription: y\n"))[0].message).toMatch(/isn't closed/);
  });

  it("reports YAML parse errors on the file's line", () => {
    // line 1 is ---, so the bad line 2 of the frontmatter is line 3 of the file
    const r = validateSkill(md("name: notes\ndescription: Use when: the user asks"), { folder: "notes" });
    const e = errors(r);
    expect(e).toHaveLength(1);
    expect(e[0].message).toMatch(/^YAML: /);
    expect(e[0].line).toBe(3);
  });

  it("flags duplicate keys", () => {
    const e = errors(validateSkill(md("name: notes\nname: notes\ndescription: d"), { folder: "notes" }));
    expect(e[0].message).toMatch(/YAML: .*unique/i);
  });

  it("checks the name against the regex and the folder", () => {
    const bad = errors(validateSkill(md("name: My Skill\ndescription: d"), { folder: "my-skill" }));
    expect(bad[0].message).toMatch(/lowercase letters, digits and dashes/);
    expect(bad[0].line).toBe(2);
    const other = errors(validateSkill(md("name: other\ndescription: d"), { folder: "my-skill" }));
    expect(other[0].message).toMatch(/match the skill's folder, "my-skill"/);
    expect(errors(validateSkill(md("description: d"), { folder: "x" }))[0].message).toMatch(/Add name: x/);
    expect(errors(validateSkill(md(`name: ${"a".repeat(65)}\ndescription: d`)))).toHaveLength(1);
  });

  it("warns when a new skill would replace an existing one", () => {
    const r = validateSkill(md("name: grill-me\ndescription: d"), { existing: ["grill-me"] });
    expect(errors(r)).toEqual([]);
    expect(r.issues[0]).toMatchObject({ severity: "warning", line: 2 });
  });

  it("requires a description of at most 1024 characters", () => {
    expect(errors(validateSkill(md("name: x"), { folder: "x" }))[0].message).toMatch(/Add description/);
    expect(errors(validateSkill(md("name: x\ndescription:"), { folder: "x" }))[0].message).toMatch(/Add description/);
    expect(errors(validateSkill(md(`name: x\ndescription: ${"d".repeat(1024)}`), { folder: "x" }))).toEqual([]);
    const long = errors(validateSkill(md(`name: x\ndescription: ${"d".repeat(1025)}`), { folder: "x" }));
    expect(long[0]).toMatchObject({ line: 3, message: "description is 1025 characters; the limit is 1024." });
    expect(errors(validateSkill(md("name: x\ndescription:\n  - a\n  - b"), { folder: "x" }))[0].message).toMatch(/must be text/);
  });

  it("warns about an empty body and non-mapping frontmatter", () => {
    expect(validateSkill(md("name: x\ndescription: d", "\n"), { folder: "x" }).issues).toMatchObject([{ severity: "warning", line: 4 }]);
    expect(errors(validateSkill(md("- a\n- b")))[0].message).toMatch(/key: value/);
  });
});
