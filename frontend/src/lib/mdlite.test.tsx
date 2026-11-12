import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { MdLite, stripMarkdown } from "./mdlite";

const html = (text: string) => renderToStaticMarkup(<MdLite text={text} />);

describe("MdLite", () => {
  it("renders inline code, bold and italic, and keeps the rest as text", () => {
    const out = html("Refactor `Inventory.cs` with **care** and *tests*, please");
    expect(out).toContain("<code");
    expect(out).toContain(">Inventory.cs</code>");
    expect(out).toContain("<strong");
    expect(out).toContain(">care</strong>");
    expect(out).toContain("<em>tests</em>");
    expect(out).toContain(", please");
  });

  it("renders fenced code blocks as pre, without the fence or language", () => {
    const out = html("Look:\n```cs\nvar x = 1;\n```\nthanks");
    expect(out).toContain("<pre");
    expect(out).toContain("var x = 1;</pre>");
    expect(out).not.toContain("```");
    expect(out).toContain("thanks");
  });

  it("escapes HTML and leaves stray markers alone", () => {
    const out = html("2 * 3 = 6 and <b>not bold</b> and a_b_c");
    expect(out).toContain("2 * 3 = 6");
    expect(out).toContain("&lt;b&gt;not bold&lt;/b&gt;");
    expect(out).not.toContain("<em>");
  });
});

describe("stripMarkdown", () => {
  it("drops code fences, backticks, emphasis, list markers and link targets", () => {
    expect(stripMarkdown("## Regex\n\nExplain `^(?:[a-z0-9]+)$` please, with **examples** and a table.")).toBe(
      "Regex Explain ^(?:[a-z0-9]+)$ please, with examples and a table.");
    expect(stripMarkdown("- [x] done\n- see [the docs](https://x.dev)")).toBe("done see the docs");
    expect(stripMarkdown("```py\nprint(1)\n```")).toBe("print(1)");
  });

  it("keeps the search highlight markers", () => {
    expect(stripMarkdown("use `\x02Merge\x03Stack` here")).toBe("use \x02Merge\x03Stack here");
  });
});
