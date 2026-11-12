#!/usr/bin/env python3
"""Parse Unity compiler output into a deduplicated, root-cause-grouped error report.

Input (auto-detected):
  * an Editor.log / batchmode -logFile log (plain text), or
  * a read_console dump (MCP for Unity 10.x): the whole tool response
    {"success":..,"data":[{type,message,file,line,stackTrace}]} or {"data":{"items":[...]}},
    a bare list of those entries, or a list of plain strings (format="plain").
  * "-" reads stdin.

Output: compact text report (default) or --json. Each issue is
  {file, line, col, code, message, severity, kind, assembly}
  kind = compile | infra | runtime.

Exit codes: 0 = no errors, 1 = compile/infra errors, 3 = only runtime errors
(exceptions etc.; use --compile-only to ignore them), 2 = bad input/usage.

Python 3.9+ stdlib only.
"""
import argparse
import json
import re
import sys
from collections import OrderedDict

# Assets/Foo.cs(12,5): error CS0103: The name 'x' does not exist in the current context
DIAG_RE = re.compile(
    r"(?P<file>[^\s:()][^:()]*?\.(?:cs|asmdef|asmref|shader|hlsl|compute|uss|uxml))"
    r"\((?P<line>\d+)(?:,(?P<col>\d+))?(?:,\d+,\d+)?\)\s*:\s*"
    r"(?P<sev>error|warning)\s+(?P<code>[A-Z]{2,3}\d{3,5})\s*:\s*(?P<msg>.*)$"
)
# Diagnostics without location (e.g. "error CS5001: Program does not contain a static 'Main' method")
BARE_DIAG_RE = re.compile(r"^(?P<sev>error|warning)\s+(?P<code>[A-Z]{2,3}\d{3,5})\s*:\s*(?P<msg>.*)$")
ASSEMBLY_RE = re.compile(r"## Script Compilation Error for: Csc \S*?/([^/\s]+)\.dll")
EXCEPTION_RE = re.compile(r"^(?P<code>(?:[A-Za-z_][\w]*\.)*[A-Za-z_]\w*Exception)(?:: (?P<msg>.*))?$")
STACK_LOC_RE = re.compile(r"\(at (?P<file>[^:()]+\.cs):(?P<line>\d+)\)")
TUNDRA_RE = re.compile(r"^\*\*\* Tundra build (success|failed)")
COMPILE_REQ_RE = re.compile(r"\[ScriptCompilation\] Requested script compilation because")

# Unity-side (non-csc) errors that block compilation. (regex, code, message template)
INFRA_PATTERNS = [
    (re.compile(r"Assembly has reference to non-existent assembly '([^']+)' \(([^)]+)\)"),
     "ASMDEF-MISSING-REF", "asmdef {1} references missing assembly '{0}'"),
    (re.compile(r"Assembly with name '([^']+)' already exists \(([^)]+)\)"),
     "ASMDEF-DUPLICATE", "duplicate assembly name '{0}' ({1})"),
    (re.compile(r"Cyclic dependencies detected between assemblies?:?\s*(.*)"),
     "ASMDEF-CYCLE", "cyclic asmdef references: {0}"),
    (re.compile(r"(?:Folder|Directory) '([^']+)' contains multiple assembly definition files"),
     "ASMDEF-MULTI", "folder {0} has more than one .asmdef"),
    (re.compile(r"An error occurred while resolving packages:?\s*(.*)"),
     "UPM-RESOLVE", "package resolution failed: {0}"),
    (re.compile(r"Unable to add package \[([^\]]+)\]"), "UPM-ADD", "cannot add package {0}"),
    (re.compile(r"Error: Could not load signature of (.*)"), "TYPELOAD", "could not load signature of {0}"),
]

# Root-cause classes, most fundamental first.
SYNTAX_CODES = {"CS1002", "CS1003", "CS1513", "CS1514", "CS1022", "CS1026", "CS1519", "CS1520", "CS1525",
                "CS1001", "CS1009", "CS1010", "CS1012", "CS1056", "CS1031", "CS1529", "CS8124", "CS1585",
                "CS1597", "CS0116", "CS1733"}
MISSING_TYPE_CODES = {"CS0246", "CS0234", "CS0400", "CS0012", "CS0518"}
DUPLICATE_CODES = {"CS0101", "CS0102", "CS0111", "CS0436", "CS0433"}
OBSOLETE_ERROR_CODES = {"CS0619"}
# Errors that can follow from a missing symbol when they name it (Roslyn already hides most cascades that come
# from an unknown type, so only group when the missing symbol appears in the message).
CASCADE_CODES = {"CS0103", "CS1061", "CS0117", "CS0115", "CS0426", "CS1503", "CS0019", "CS0266", "CS7036",
                 "CS0120", "CS0122", "CS1729", "CS0311", "CS0315", "CS0305", "CS0308"}

QUOTED_RE = re.compile(r"'([^']+)'")

# Known Unity 6000.3 renames/moves (observed on 6000.3.21f1; see references/common-errors.md).
HINTS = [
    (re.compile(r"'Cinemachine'"), "Cinemachine 3.x: namespace is Unity.Cinemachine (using Unity.Cinemachine;)"),
    (re.compile(r"'Cinemachine(VirtualCamera|FreeLook)'"), "Cinemachine 3.x: use CinemachineCamera (Unity.Cinemachine)"),
    (re.compile(r"'(Light2D|ShadowCaster2D)'.*Experimental"), "URP: Light2D is in UnityEngine.Rendering.Universal"),
    (re.compile(r"'InputSystem' does not exist in the namespace 'UnityEngine'"),
     "add \"Unity.InputSystem\" to the asmdef references (or install com.unity.inputsystem)"),
    (re.compile(r"'(TextMeshProUGUI|TMP_Text|TextMeshPro)'"), "TextMeshPro is in com.unity.ugui 2.x: add \"Unity.TextMeshPro\" asmdef reference"),
    (re.compile(r"'(Test|UnityTest|TestFixture|SetUp|TearDown)(Attribute)?'"),
     "test asmdef: references UnityEngine.TestRunner/UnityEditor.TestRunner, overrideReferences + nunit.framework.dll, UNITY_INCLUDE_TESTS"),
    (re.compile(r"autoSimulation"), "use Physics2D.simulationMode = SimulationMode2D.Script/FixedUpdate"),
    (re.compile(r"name 'UnityEditor' could not be found|'UnityEditor' does not exist"), "UnityEditor in a runtime assembly: move the code to an Editor folder/asmdef or wrap in #if UNITY_EDITOR"),
]


def hint_for(message):
    for rx, h in HINTS:
        if rx.search(message):
            return h
    return ""

NOISE_RE = re.compile(r"Access token is unavailable|\[Licensing::|Curl error|LicensingClient", re.I)


def norm_path(p):
    p = (p or "").strip().replace("\\", "/")
    for root in ("/Assets/", "/Packages/", "/Library/PackageCache/"):
        i = p.find(root)
        if i > 0:
            return p[i + 1:]
    return p


def make_issue(file, line, col, code, msg, sev, kind, assembly=""):
    return OrderedDict([("file", norm_path(file)), ("line", int(line or 0)), ("col", int(col or 0)),
                        ("code", code), ("message", (msg or "").strip()), ("severity", sev),
                        ("kind", kind), ("assembly", assembly or "")])


def parse_line(text, assembly=""):
    """Return an issue for one log/console line, or None."""
    s = text.strip()
    if not s or NOISE_RE.search(s):
        return None
    m = DIAG_RE.search(s)
    if m:
        kind = "compile" if m.group("code").startswith(("CS", "BC")) else "infra"
        return make_issue(m.group("file"), m.group("line"), m.group("col"), m.group("code"), m.group("msg"),
                          m.group("sev"), kind, assembly)
    m = BARE_DIAG_RE.match(s)
    if m:
        return make_issue("", 0, 0, m.group("code"), m.group("msg"), m.group("sev"), "compile", assembly)
    for rx, code, tmpl in INFRA_PATTERNS:
        m = rx.search(s)
        if m:
            g = m.groups()
            file = ""
            for part in g:
                if part and part.endswith((".asmdef", ".asmref")):
                    file = part
            return make_issue(file, 0, 0, code, tmpl.format(*g), "error", "infra")
    m = EXCEPTION_RE.match(s)
    if m:
        return make_issue("", 0, 0, m.group("code").split(".")[-1], m.group("msg") or "", "error", "runtime")
    return None


def last_compile_slice(lines):
    """Lines belonging to the most recent script compilation in a long Editor.log (heuristic)."""
    tundra = [i for i, l in enumerate(lines) if TUNDRA_RE.match(l)]
    if not tundra:
        return lines
    last = tundra[-1]
    start = 0
    for i in range(last - 1, -1, -1):
        if TUNDRA_RE.match(lines[i]) or COMPILE_REQ_RE.search(lines[i]):
            start = i if COMPILE_REQ_RE.search(lines[i]) else i + 1
            break
    end = len(lines)
    for i in range(last + 1, len(lines)):
        if COMPILE_REQ_RE.search(lines[i]):
            end = i
            break
    return lines[start:end]


def parse_text(text, last_compile=False):
    lines = text.splitlines()
    if last_compile:
        lines = last_compile_slice(lines)
    issues, assembly, pending_exc = [], "", None
    for raw in lines:
        m = ASSEMBLY_RE.search(raw)
        if m:
            assembly = m.group(1)
            continue
        if pending_exc is not None:
            loc = STACK_LOC_RE.search(raw)
            if loc and not pending_exc["file"]:
                pending_exc["file"], pending_exc["line"] = norm_path(loc.group("file")), int(loc.group("line"))
            if not raw.strip():
                pending_exc = None
            if loc or raw.startswith(("  at ", "UnityEngine.", "UnityEditor.", "System.")) or "(at " in raw:
                continue
        it = parse_line(raw, assembly)
        if it:
            issues.append(it)
            pending_exc = it if it["kind"] == "runtime" else None
    return issues


def console_entries(obj):
    if isinstance(obj, dict):
        if "result" in obj and isinstance(obj["result"], (dict, list)):  # some clients wrap once more
            return console_entries(obj["result"])
        data = obj.get("data", obj.get("items", obj.get("lines")))
        if isinstance(data, dict):
            data = data.get("items", data.get("lines", []))
        if data is None and ("message" in obj or "type" in obj):
            data = [obj]
        return data or []
    if isinstance(obj, list):
        return obj
    return []


def parse_console_json(obj):
    issues = []
    for e in console_entries(obj):
        if isinstance(e, str):
            it = parse_line(e)
            if it:
                issues.append(it)
            continue
        if not isinstance(e, dict):
            continue
        msg = str(e.get("message", ""))
        typ = str(e.get("type", "")).lower()
        stack = e.get("stackTrace") or e.get("stacktrace") or ""
        first = msg.strip().splitlines()[0] if msg.strip() else ""
        it = parse_line(first)
        if it is None and typ in ("error", "exception", "assert"):
            it = make_issue(e.get("file", ""), e.get("line", 0), 0,
                            "EXCEPTION" if typ == "exception" else typ.upper(), first, "error", "runtime")
        elif it is None and typ == "warning" and first:
            it = make_issue(e.get("file", ""), e.get("line", 0), 0, "WARNING", first, "warning", "runtime")
        if it is None:
            continue
        if not it["file"] and e.get("file"):
            it["file"], it["line"] = norm_path(e["file"]), int(e.get("line") or 0)
        if not it["file"] and stack:
            loc = STACK_LOC_RE.search(stack)
            if loc:
                it["file"], it["line"] = norm_path(loc.group("file")), int(loc.group("line"))
        issues.append(it)
    return issues


def dedupe(issues):
    seen, out = {}, []
    for it in issues:
        key = (it["file"], it["line"], it["col"], it["code"], it["message"])
        if key not in seen:
            seen[key] = it
            out.append(it)
        elif it.get("assembly") and not seen[key].get("assembly"):
            seen[key]["assembly"] = it["assembly"]  # the csc section names the assembly after the first echo
    return out


def group_root_causes(errors):
    """Return ordered list of groups: {rank, cause, root, members}."""
    groups = OrderedDict()

    def add(key, rank, cause, it):
        g = groups.get(key)
        if g is None:
            g = groups[key] = {"rank": rank, "cause": cause, "root": it, "members": []}
        g["members"].append(it)

    missing_syms = {}
    for it in errors:
        code = it["code"]
        sym = QUOTED_RE.search(it["message"])
        sym = sym.group(1) if sym else ""
        if it["kind"] == "infra":
            add(("infra", code, it["message"]), 0, "project/asmdef/package problem", it)
        elif code in SYNTAX_CODES:
            add(("syntax", it["file"]), 1, "syntax error (fix the first one in the file; the rest often cascade)", it)
        elif code in MISSING_TYPE_CODES:
            asm = it.get("assembly") or ""
            hint = "using, asmdef reference, package, or renamed API"
            if asm and not asm.startswith("Assembly-CSharp"):
                hint = "check the references of the %s .asmdef first; then using/package/renamed API" % asm
            add(("missing", sym or it["message"]), 2, "missing type/namespace '%s' (%s)" % (sym, hint), it)
            if sym:
                missing_syms[sym] = ("missing", sym)
        elif code in DUPLICATE_CODES:
            add(("dup", sym or it["message"]), 3, "duplicate definition '%s' (duplicate file/class or assembly)" % sym, it)
        elif code in OBSOLETE_ERROR_CODES:
            add(("obsolete", sym or it["message"]), 4, "API removed/obsolete-as-error '%s'" % sym, it)
    for it in errors:
        code = it["code"]
        if it["kind"] == "infra" or code in SYNTAX_CODES | MISSING_TYPE_CODES | DUPLICATE_CODES | OBSOLETE_ERROR_CODES:
            continue
        if code in CASCADE_CODES:
            hit = next((k for sym, k in missing_syms.items() if "'%s'" % sym in it["message"]), None)
            if hit:
                groups[hit]["members"].append(dict(it, cascade=True))
                continue
        if it["kind"] == "runtime":
            add(("runtime", it["code"], it["message"]), 6, "runtime/console error", it)
        else:
            add(("file", it["file"]), 5, "first error in %s" % (it["file"] or "<unknown file>"), it)
    return sorted(groups.values(), key=lambda g: g["rank"])


def fmt(it):
    loc = it["file"] or "<no file>"
    if it["line"]:
        loc += "(%d%s)" % (it["line"], ",%d" % it["col"] if it["col"] else "")
    asm = " [%s]" % it["assembly"] if it.get("assembly") else ""
    return "%s: %s %s: %s%s" % (loc, it["severity"], it["code"], it["message"], asm)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="Editor.log / batchmode log / read_console JSON dump, or - for stdin")
    ap.add_argument("--json", action="store_true", help="print machine-readable JSON instead of text")
    ap.add_argument("--last-compile", action="store_true",
                    help="text logs only: consider just the most recent compilation (long-lived Editor.log)")
    ap.add_argument("--compile-only", action="store_true", help="ignore runtime/console errors for the exit code")
    ap.add_argument("--warnings", action="store_true", help="list warnings too (always counted)")
    ap.add_argument("--max", type=int, default=30, help="max issues listed per section (default 30)")
    a = ap.parse_args(argv)

    try:
        raw = sys.stdin.read() if a.input == "-" else open(a.input, encoding="utf-8", errors="replace").read()
    except OSError as e:
        print("RESULT: FAIL cannot read input: %s" % e)
        return 2
    stripped = raw.lstrip()
    issues = None
    if stripped[:1] in "[{":
        try:
            issues = parse_console_json(json.loads(stripped))
        except ValueError:
            issues = None
    if issues is None:
        issues = parse_text(raw, a.last_compile)
    issues = dedupe(issues)

    errors = [i for i in issues if i["severity"] == "error"]
    warnings = [i for i in issues if i["severity"] == "warning"]
    compile_errors = [i for i in errors if i["kind"] in ("compile", "infra")]
    runtime_errors = [i for i in errors if i["kind"] == "runtime"]
    groups = group_root_causes(errors)

    if compile_errors:
        code = 1
    elif runtime_errors and not a.compile_only:
        code = 3
    else:
        code = 0

    if a.json:
        out = OrderedDict([
            ("compile_errors", len(compile_errors)), ("runtime_errors", len(runtime_errors)),
            ("warnings", len(warnings)), ("exit_code", code),
            ("root_causes", [OrderedDict([("cause", g["cause"]), ("hint", hint_for(g["root"]["message"])),
                                          ("root", g["root"]), ("count", len(g["members"]))]) for g in groups]),
            ("errors", errors), ("warning_list", warnings if a.warnings else []),
        ])
        print(json.dumps(out, indent=1))
        return code

    print("compile errors: %d | runtime errors: %d | warnings: %d | root causes: %d"
          % (len(compile_errors), len(runtime_errors), len(warnings), len(groups)))
    if groups:
        print("\nROOT CAUSES (fix in this order):")
        for n, g in enumerate(groups[: a.max], 1):
            extra = len(g["members"]) - 1
            print("%2d. %s" % (n, g["cause"]))
            h = hint_for(g["root"]["message"])
            if h:
                print("    hint: " + h)
            print("    %s%s" % (fmt(g["root"]), "  (+%d related)" % extra if extra > 0 else ""))
        print("\nALL ERRORS (deduplicated):")
        for it in errors[: a.max]:
            print("  " + fmt(it))
        if len(errors) > a.max:
            print("  ... %d more" % (len(errors) - a.max))
    if a.warnings and warnings:
        print("\nWARNINGS:")
        for it in warnings[: a.max]:
            print("  " + fmt(it))
    if code == 0:
        print("RESULT: OK")
    elif code == 1:
        print("RESULT: FAIL %d compile error(s), %d root cause(s)" % (len(compile_errors), len(groups)))
    else:
        print("RESULT: FAIL %d runtime/console error(s), 0 compile errors" % len(runtime_errors))
    return code


if __name__ == "__main__":
    sys.exit(main())
