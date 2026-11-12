// GateRow's text helpers: the gate message the model gets is split into a readable reason and the
// quoted evidence, without the untrusted markers.
import { describe, expect, it } from "vitest";
import { gateSummary, splitGateText } from "./GateRow";

describe("splitGateText", () => {
  it("drops the gate prefix and the untrusted markers", () => {
    const text = "[GameDevWorkstation gate unity.compile] 3 compile errors after this turn's changes (mcp). Fix them.\n\n"
      + '<untrusted-1a2b source="unity:unity.compile">\nAssets/A.cs(3,1): error CS0103\n</untrusted-1a2b>';
    const { reason, evidence } = splitGateText(text, "unity.compile");
    expect(reason).toBe("3 compile errors after this turn's changes (mcp). Fix them.");
    expect(evidence).toBe("Assets/A.cs(3,1): error CS0103");
  });

  it("keeps plain text as the reason", () => {
    expect(splitGateText("[GameDevWorkstation gate x] it failed", "x")).toEqual({ reason: "it failed", evidence: "" });
  });

  it("drops the prefix of messages saved under the app's previous name, only for this gate", () => {
    expect(splitGateText("[Oldname gate x] it failed", "x")).toEqual({ reason: "it failed", evidence: "" });
    expect(splitGateText("[Oldname gate y] it failed", "x").reason).toBe("[Oldname gate y] it failed");
  });
});

describe("gateSummary", () => {
  it("cuts at the first sentence or 'after this turn'", () => {
    expect(gateSummary("3 compile errors after this turn's changes (mcp). Fix them.")).toBe("3 compile errors");
    expect(gateSummary("Tests failed. Fix the code.")).toBe("Tests failed");
  });

  it("shortens long reasons", () => {
    const s = gateSummary("x".repeat(200));
    expect(s.length).toBe(70);
    expect(s.endsWith("…")).toBe(true);
  });
});
