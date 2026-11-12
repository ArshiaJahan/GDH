#!/usr/bin/env python3
"""Heuristic Unity C# performance audit; Python 3.9+, standard library only.

Scan Assets (or a standalone C# folder), trace two same-file call levels and one
terminal cross-file level.
Names are resolved conservatively (all matching overloads), without a C# compiler.
Scores count distinct sites times the largest reachable callback frequency, not
bytes or timings. Non-hot lifecycle/API checks receive frequency 1.

JSON goes to stdout with its RESULT footer on stderr, like perf_report.py.
Text/Markdown put the footer on stdout. Baselines use source text, never line
numbers. --update-baseline explicitly accepts a full-project snapshot, even
when --changed restricts the displayed findings.
"""

import argparse
from bisect import bisect_right
from collections import defaultdict, deque
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import sys
from typing import Dict, List, Tuple


HOT_METHOD = re.compile(r"^(?:Update|FixedUpdate|LateUpdate|OnGUI|On\w*Stay\w*)$")
CALL = re.compile(r"\b([A-Za-z_]\w*)\s*(?:<[^;{}()=]+>)?\s*\(")
CONTROL = {"if", "for", "foreach", "while", "switch", "catch", "using", "lock",
           "nameof", "typeof", "sizeof", "default", "checked", "unchecked"}
RULES = {
    "HOT_GETCOMPONENT": r"\b(?:GetComponent(?:s)?(?:InChildren|InParent)?|TryGetComponent)\s*(?:<[^;{}()]+>)?\s*\(",
    "HOT_FIND": r"\b(?:GameObject\s*\.\s*Find\w*|FindObjects?OfType|FindObjectsByType|FindFirstObjectByType|FindAnyObjectByType)\s*(?:<[^;{}()]+>)?\s*\(",
    "HOT_CAMERA_MAIN": r"\bCamera\s*\.\s*main\b",
    "HOT_LINQ": r"\.\s*(?:Where|Select|SelectMany|Any|All|ToList|ToArray|ToDictionary|ToLookup|OrderBy|OrderByDescending|ThenBy|ThenByDescending|First|FirstOrDefault|Last|LastOrDefault|Single|SingleOrDefault|Count|Sum|Average|Min|Max|Aggregate|GroupBy|Distinct|Union|Intersect|Except|Concat|Skip|Take|Reverse|OfType|Cast)\s*(?:<[^;{}()]+>)?\s*\(",
    "HOT_NEW_COLLECTION": r"\bnew\s+(?:(?:(?:System\s*\.\s*Collections\s*\.\s*Generic\s*\.)?(?:List|Dictionary|HashSet))\s*<|(?:[\w.]+(?:\s*<[^;{}()]+>)?\s*)?\[)",
    "HOT_INSTANTIATE_DESTROY": r"\b(?:Instantiate|Destroy)\s*(?:<[^;{}()]+>)?\s*\(",
    # Lambdas, anonymous methods and explicit delegate construction all allocate.
    "HOT_LAMBDA": r"=>|\bdelegate\s*(?:\([^)]*\)\s*)?\{|\bnew\s+(?:(?:global\s*::\s*)?\w+\s*\.\s*)*"
                  r"(?:Action|Func|Predicate|Comparison|Converter|EventHandler|UnityAction)\s*(?:<[^;{}()]+>)?\s*\(",
    "HOT_DEBUG_LOG": r"\bDebug\s*\.\s*Log\w*\s*\(",
    "HOT_SENDMESSAGE": r"\b(?:SendMessage|BroadcastMessage)\s*\(",
    "HOT_RESOURCES_LOAD": r"\bResources\s*\.\s*Load(?:All|Async)?\s*(?:<[^;{}()]+>)?\s*\(",
    "TAG_STRING_COMPARE": r"\.\s*tag\s*==|==\s*(?:\w+\s*\.\s*)+tag\b",
    "NONALLOC_DEPRECATED": r"\bPhysics2D\s*\.\s*\w*NonAlloc\s*\(",
}
RULE_IDS = frozenset(RULES) | {
    "HOT_STRING_ALLOC", "COROUTINE_NEW_WAIT", "EVENT_NO_UNSUBSCRIBE", "OBSOLETE_VELOCITY",
}
PATTERNS = {rule: re.compile(pattern) for rule, pattern in RULES.items()}
STRING_START = re.compile(r'(?:\$+@?|@\$?)?"|\x27')
RAW_QUOTES = re.compile(r'"{3,}')


@dataclass
class Literal:
    start: int
    end: int
    interpolated: bool
    is_string: bool


@dataclass
class Method:
    name: str
    class_name: str
    class_start: int
    start: int
    end: int
    file: str
    declaration_start: int
    parameters_start: int
    parameters_end: int
    class_identity: str

    @property
    def qualified(self):
        return self.class_name + "." + self.name


@dataclass
class Source:
    file: str
    text: str
    code: str
    uncommented: str
    literals: List[Literal]
    comments: List[Tuple[int, str]]
    pairs: Dict[int, int]
    methods: List[Method] = field(default_factory=list)
    newlines: List[int] = field(default_factory=list)
    class_fields: Dict[int, str] = field(default_factory=dict)

    def line(self, offset):
        return bisect_right(self.newlines, offset - 1) + 1


def literal_end(text, match):
    """Consume one literal, including nested quotes in interpolation expressions."""
    prefix = match.group()
    quote = match.end() - 1
    char = text[quote]
    raw = RAW_QUOTES.match(text, quote) if char == '"' else None
    if raw:
        close = text.find(raw.group(), raw.end())
        return len(text) if close < 0 else close + len(raw.group())
    pos = quote + 1
    interpolation_depth = 0
    while pos < len(text):
        if interpolation_depth:
            nested = STRING_START.match(text, pos)
            if nested:
                pos = literal_end(text, nested)
                continue
            if text.startswith("/*", pos):
                close = text.find("*/", pos + 2)
                pos = len(text) if close < 0 else close + 2
                continue
            if text.startswith("//", pos):
                close = text.find("\n", pos + 2)
                pos = len(text) if close < 0 else close
                continue
            if text[pos] == "{":
                interpolation_depth += 1
            elif text[pos] == "}":
                interpolation_depth -= 1
        elif "$" in prefix and text[pos] == "{":
            if text.startswith("{{", pos):
                pos += 2
                continue
            interpolation_depth = 1
        elif text[pos] == char:
            if "@" in prefix and text.startswith(char * 2, pos):
                pos += 2
                continue
            return pos + 1
        elif text[pos] == "\\" and "@" not in prefix:
            pos += 2
            continue
        pos += 1
    return len(text)


def lex(text):
    """Mask comments/literals with spaces, retaining offsets and newline positions.

    Keep comments separately for suppression and literal spans for allocation
    checks. Literal contents can never introduce fake calls or braces. Handles
    regular, character, verbatim, interpolated and C# raw strings.
    """
    code = list(text)
    uncommented = list(text)
    literals, comments = [], []

    def blank(target, start, end):
        for pos in range(start, end):
            if text[pos] not in "\r\n":
                target[pos] = " "

    i = 0
    while i < len(text):
        if text.startswith("//", i) or text.startswith("/*", i):
            if text.startswith("//", i):
                end = text.find("\n", i)
                end = len(text) if end < 0 else end
            else:
                end = text.find("*/", i + 2)
                end = len(text) if end < 0 else end + 2
            comments.append((i, text[i:end]))
            blank(code, i, end)
            blank(uncommented, i, end)
            i = end
            continue
        match = STRING_START.match(text, i)
        if not match:
            i += 1
            continue
        end = literal_end(text, match)
        literals.append(Literal(i, end, "$" in match.group(), text[match.end() - 1] == '"'))
        blank(code, i, end)
        i = end
    return "".join(code), "".join(uncommented), literals, comments


def delimiter_pairs(code):
    pairs, stack = {}, []
    for pos, char in enumerate(code):
        if char in "({[":
            stack.append((char, pos))
        elif char in ")}]" and stack and stack[-1][0] == {")": "(", "}": "{", "]": "["}[char]:
            _, start = stack.pop()
            pairs[start] = pos
    return pairs


def statement_end(code, pairs, start):
    """Exclusive end of a block or single statement, skipping nested delimiters."""
    while start < len(code) and code[start].isspace():
        start += 1
    if start < len(code) and code[start] == "{":
        return pairs.get(start, len(code) - 1) + 1
    control = re.match(r"(if|for|foreach|while|switch|using|lock|fixed)\s*\(", code[start:])
    if control:
        opening = start + control.end() - 1
        if opening in pairs:
            end = statement_end(code, pairs, pairs[opening] + 1)
            if control.group(1) == "if":
                otherwise = re.match(r"\s*else\b", code[end:])
                if otherwise:
                    end = statement_end(code, pairs, end + otherwise.end())
            return end
    do = re.match(r"do\b", code[start:])
    if do:
        end = statement_end(code, pairs, start + do.end())
        tail = re.match(r"\s*while\s*\(", code[end:])
        if tail:
            opening = end + tail.end() - 1
            if opening in pairs:
                semicolon = re.match(r"\s*;", code[pairs[opening] + 1:])
                return pairs[opening] + 1 + (semicolon.end() if semicolon else 0)
        return end
    pos = start
    while pos < len(code):
        if code[pos] == ";":
            return pos + 1
        pos = pairs[pos] + 1 if pos in pairs else pos + 1
    return len(code)


def parse_source(file, text):
    code, uncommented, literals, comments = lex(text)
    pairs = delimiter_pairs(code)
    source = Source(file, text, code, uncommented, literals, comments, pairs)
    source.newlines = [match.start() for match in re.finditer("\n", text)]
    classes = []
    for match in re.finditer(r"\b(?:class|struct|record)\s+(\w+)[^;{}]*\{", code):
        opening = match.end() - 1
        if opening in pairs:
            classes.append((opening, pairs[opening], match.group(1)))
    namespaces = []
    for match in re.finditer(r"\bnamespace\s+(\w+(?:\s*\.\s*\w+)*)\s*([;{])", code):
        opening = match.end() - 1
        end = pairs.get(opening, len(code)) if match.group(2) == "{" else len(code)
        namespaces.append((opening, end, re.sub(r"\s+", "", match.group(1))))
    identities = {}
    for opening, _, name in classes:
        namespace = [n[2] for n in namespaces if n[0] < opening < n[1]]
        enclosing = [c[2] for c in classes if c[0] < opening < c[1]]
        identities[opening] = ".".join(namespace + enclosing + [name])
    # The innermost containing brace must be the class, not a method/initializer.
    parents, stack = {}, []
    for pos, char in enumerate(code):
        if char == "{":
            stack.append(pos)
        elif char == "}" and stack:
            stack.pop()
        elif char == "(":
            parents[pos] = stack[-1] if stack else None
    for match in CALL.finditer(code):
        name = match.group(1)
        opening = match.end() - 1
        if name in CONTROL or opening not in pairs:
            continue
        owners = [c for c in classes if c[0] == parents.get(opening)]
        if not owners:
            continue
        owner = owners[-1]
        close = pairs[opening]
        after = re.match(r"\s*(?:where\s+[^{};=]+)?\s*(\{|=>)", code[close + 1:])
        if not after:
            continue
        # Exclude calls in field initializers and attributes.
        boundary = max(code.rfind(char, owner[0], match.start()) for char in ";{}")
        header = code[boundary + 1:match.start()]
        # Named attribute arguments are not field initializers.
        header = re.sub(r"\[[^\]]*\]", "", header)
        if "=" in header or header.rstrip().endswith("."):
            continue
        start = close + 1 + after.end()
        if after.group(1) == "{":
            end = pairs.get(start - 1)
            if end is None:
                continue
        else:
            end = statement_end(code, pairs, start)
        source.methods.append(Method(name, owner[2], owner[0], start, end, file,
                                     boundary + 1, opening + 1, close, identities[owner[0]]))
    return source


def method_calls(source, method):
    for match in CALL.finditer(source.code, method.start, method.end):
        if match.group(1) in CONTROL:
            continue
        # Construction is not a method-name call edge.
        if re.search(r"\bnew\s+$", source.code[method.start:match.start()]):
            continue
        yield match.group(1)


def hot_contexts(sources):
    index = defaultdict(list)
    by_file = {source.file: source for source in sources}
    for source in sources:
        for method in source.methods:
            index[method.name].append(method)
    contexts = defaultdict(set)
    for source in sources:
        for root in source.methods:
            if not HOT_METHOD.fullmatch(root.name):
                continue
            frequency = 3 if re.fullmatch(r"On\w*Stay\w*", root.name) else 1
            queue = deque([(root, 0, ())])
            seen = set()
            while queue:
                method, depth, via = queue.popleft()
                state = (method.file, method.start, depth, via)
                if state in seen:
                    continue
                seen.add(state)
                contexts[(method.file, method.start)].add((root.qualified, frequency, via))
                if method.file != root.file:
                    continue  # One terminal cross-file edge.
                for name in set(method_calls(by_file[method.file], method)):
                    for callee in index[name]:
                        if callee.file == method.file:
                            if depth < 2:
                                queue.append((callee, depth + 1, via + (callee.qualified,)))
                        else:
                            queue.append((callee, depth, via + (callee.qualified,)))
    return contexts


def loop_bodies(source, method):
    code = source.code
    for match in re.finditer(r"\b(?:for|foreach|while)\s*\(|\bdo\b", code[method.start:method.end]):
        start = method.start + match.end()
        if match.group().lstrip().startswith("do"):
            body = start
        else:
            opening = start - 1
            if opening not in source.pairs:
                continue
            body = source.pairs[opening] + 1
        end = min(statement_end(code, source.pairs, body), method.end)
        yield body, end


def normalized_line(text):
    """Whitespace normalization preserves spaces *inside* string literals."""
    code, uncommented, literals, _ = lex(text)
    parts, start = [], 0
    for literal in literals:
        parts.extend(re.findall(r"\w+|[^\w\s]", code[start:literal.start]))
        parts.append(uncommented[literal.start:literal.end])
        start = literal.end
    parts.extend(re.findall(r"\w+|[^\w\s]", code[start:]))
    return " ".join(parts)


def baseline_key(finding):
    return json.dumps([finding["rule"], finding["file"], normalized_line(finding["line_text"])],
                      ensure_ascii=False, separators=(",", ":"))


def suppressed_lines(source):
    allowed = defaultdict(set)
    for offset, comment in source.comments:
        match = re.fullmatch(r"//\s*harness:allow\s+(\w+)\s+(\S[^\r\n]*)\s*", comment)
        if match:
            line = source.line(offset)
            allowed[line].add(match.group(1))
            allowed[line + 1].add(match.group(1))
    return allowed


def class_fields(source, method):
    """Class declarations, with method bodies/signatures and nested types masked."""
    if method.class_start in source.class_fields:
        return source.class_fields[method.class_start]
    start = method.class_start + 1
    end = source.pairs[method.class_start]
    fields = list(source.code[start:end])

    def mask(first, last):
        fields[first - start:last - start] = " " * (last - first)

    for other in source.methods:
        if other.class_start == method.class_start:
            mask(other.declaration_start, min(other.end + 1, end))
    for nested in re.finditer(r"\b(?:class|struct|record)\s+\w+[^;{}]*\{", source.code[start:end]):
        opening = start + nested.end() - 1
        if opening in source.pairs:
            mask(start + nested.start(), source.pairs[opening] + 1)
    result = "".join(fields)
    source.class_fields[method.class_start] = result
    return result


def declared_names(declarations, type_pattern):
    """Collect every declarator, skipping commas inside initializer expressions."""
    pairs = delimiter_pairs(declarations)
    names = set()
    for declaration in re.finditer(r"\b(?:" + type_pattern + r")\s+(\w+)", declarations):
        names.add(declaration.group(1))
        pos = declaration.end()
        while pos < len(declarations) and declarations[pos] not in ";){}":
            if declarations[pos] == ",":
                following = re.match(r"\s*(\w+)\s*(?=[,;=])", declarations[pos + 1:])
                if following:
                    names.add(following.group(1))
            pos = pairs[pos] + 1 if pos in pairs else pos + 1
    return names


def marked_code(source):
    """Code with each literal's first character replaced by a type marker.

    \x01 marks a string literal and \x02 a character literal; the remaining
    literal characters stay blank, so offsets match source.code.
    """
    marked = list(source.code)
    for literal in source.literals:
        marked[literal.start] = "\x01" if literal.is_string else "\x02"
    return "".join(marked)


def string_sites(source, method):
    body = source.code[method.start:method.end]
    for match in re.finditer(r"\bstring\s*\.\s*Format\s*\(|\.\s*ToString\s*\(", body):
        yield method.start + match.start()
    strings = [literal for literal in source.literals
               if literal.is_string and method.start <= literal.start < method.end]
    for literal in strings:
        if literal.interpolated:
            yield literal.start
    # Token markers retain string *positions*, never their contents.
    marked = marked_code(source)
    declarations = class_fields(source, method) + ";" + source.code[method.parameters_start:method.end]
    names = declared_names(declarations, r"string|String")
    names.update(re.findall(r"\bvar\s+(\w+)\s*=\s*(?:\x01|string\s*\.\s*Empty)", marked[method.start:method.end]))
    closing_pairs = {end: start for start, end in source.pairs.items()}

    def string_operand(start, end):
        # Only grouping parentheses are transparent. A call's arguments do not
        # establish its return type, even when the argument is a string.
        while start < end:
            while start < end and marked[start].isspace():
                start += 1
            while start < end and marked[end - 1].isspace():
                end -= 1
            if start < end and marked[start] == "(" and source.pairs.get(start) == end - 1:
                start, end = start + 1, end - 1
            else:
                break
        token = marked[start:end]
        return token == "\x01" or token in names

    for match in re.finditer(r"(?<!\+)\+(?!\+)", body):
        pos = method.start + match.start()
        left = re.search(r"(\w+|\x01|\))\s*$", marked[method.start:pos])
        right = re.match(r"\s*=?\s*(\w+|\x01|\()", marked[pos + 1:method.end])
        operands = []
        if left:
            start, end = method.start + left.start(1), method.start + left.end(1)
            if left.group(1) == ")":
                start = closing_pairs.get(end - 1, end)
                prefix = marked[method.start:start].rstrip()
                word = re.search(r"\b(\w+)$", prefix)
                keyword = word and word.group(1) in CONTROL | {"return", "throw", "yield", "await"}
                if prefix and not keyword and (prefix[-1].isalnum() or prefix[-1] in "_)]>"):
                    start = end  # Invocation, indexing or cast, not grouping.
            operands.append((start, end))
        if right:
            start, end = pos + 1 + right.start(1), pos + 1 + right.end(1)
            if right.group(1) == "(":
                end = source.pairs.get(start, start - 1) + 1
            operands.append((start, end))
        if any(string_operand(start, end) for start, end in operands):
            yield pos


def velocity_sites(source, method):
    # Fields in the same class plus this method's parameters/locals. Keep other
    # classes and other methods' locals out of the type-name approximation.
    body = source.code[method.start:method.end]
    declarations = class_fields(source, method) + ";" + source.code[method.parameters_start:method.parameters_end] + ";" + body
    declaration_pairs = delimiter_pairs(declarations)
    names = set()
    for declaration in re.finditer(r"\bRigidbody2D\s+(\w+)", declarations):
        names.add(declaration.group(1))
        pos = declaration.end()
        # Also recognize `Rigidbody2D left, right = GetBody();`.
        while pos < len(declarations) and declarations[pos] not in ";){}":
            if declarations[pos] == ",":
                following = re.match(r"\s*(\w+)\s*(?=[,;=])", declarations[pos + 1:])
                if following:
                    names.add(following.group(1))
            pos = declaration_pairs[pos] + 1 if pos in declaration_pairs else pos + 1
    names.update(re.findall(r"\bvar\s+(\w+)\s*=\s*(?:\w+\s*\.\s*)?(?:GetComponent|GetComponentInChildren|GetComponentInParent)\s*<\s*Rigidbody2D\s*>", body))
    for match in re.finditer(r"\b(\w+)\s*\.\s*velocity\b", body):
        if match.group(1) in names:
            yield method.start + match.start()


def scan_sources(sources):
    contexts = hot_contexts(sources)
    findings = []
    subscriptions = defaultdict(set)
    event_pattern = re.compile(r"\b(\w+(?:\s*\.\s*\w+)*)\s*(\+=|-=)\s*([^;]+);")

    def event_key(match):
        return tuple(re.sub(r"\bthis\.", "", re.sub(r"\s+", "", value))
                     for value in (match.group(1), match.group(3)))

    # Partial declarations share a class identity even across source files.
    # Collect teardown handlers before checking any initialization method.
    for source in sources:
        for method in source.methods:
            if method.name in {"OnDisable", "OnDestroy"}:
                for match in event_pattern.finditer(source.code, method.start, method.end):
                    if match.group(2) == "-=":
                        subscriptions[method.class_identity].add(event_key(match))
    for source in sources:
        allowed = suppressed_lines(source)
        lines = source.text.splitlines()
        for method in source.methods:
            hot = contexts.get((source.file, method.start), set())
            sites = defaultdict(set)

            def add(rule, offset):
                line = source.line(offset)
                if rule not in allowed[line]:
                    sites[(rule, line)].add(offset)

            for rule, pattern in PATTERNS.items():
                if rule.startswith("HOT_") and not hot:
                    continue
                if rule == "HOT_LINQ" and not re.search(r"\busing\s+(?:global\s*::\s*)?System\s*\.\s*Linq\s*;", source.code):
                    continue
                for match in pattern.finditer(source.code, method.start, method.end):
                    add(rule, match.start())
            if hot:
                for offset in string_sites(source, method):
                    add("HOT_STRING_ALLOC", offset)
            for start, end in loop_bodies(source, method):
                for match in re.finditer(r"\bnew\s+WaitForSeconds(?:Realtime)?\s*\(", source.code[start:end]):
                    add("COROUTINE_NEW_WAIT", start + match.start())
            for offset in velocity_sites(source, method):
                add("OBSOLETE_VELOCITY", offset)
            if method.name in {"OnEnable", "Awake", "Start"}:
                # += is also arithmetic/string assignment; explicitly declared
                # scalar operands and known Unity value properties are not events.
                declarations = class_fields(source, method) + ";" + source.code[method.parameters_start:method.end]
                scalars = declared_names(declarations,
                    r"bool|byte|sbyte|short|ushort|int|uint|long|ulong|float|double|decimal|char|string|String|Vector[234]|Quaternion|Color")
                # `var` locals initialized from numeric, string, char or bool
                # literals (or string.Empty) are scalars, not delegates.
                marked = marked_code(source)
                scalars.update(re.findall(
                    r"\bvar\s+(\w+)\s*=\s*(?:[\x01\x02]|-?\s*\d|true\b|false\b|(?:string|String)\s*\.\s*Empty\b)",
                    marked[method.parameters_start:method.end]))
                transforms = declared_names(declarations, r"Transform|RectTransform") | {"transform"}
                for match in event_pattern.finditer(source.code, method.start, method.end):
                    key = event_key(match)
                    # A literal right-hand side is never an event handler.
                    if re.match(r"\s*(?:[\x01\x02]|\d|true\b|false\b)", marked[match.end(2):match.end(3)]):
                        continue
                    receiver, _, member = key[0].rpartition(".")
                    value_member = (
                        (receiver in scalars and member in {"x", "y", "z", "w", "r", "g", "b", "a"}) or
                        ((receiver in transforms or receiver.endswith(".transform")) and member in {
                            "position", "localPosition", "eulerAngles", "localEulerAngles", "localScale",
                            "right", "up", "forward", "anchoredPosition", "anchoredPosition3D",
                            "sizeDelta", "offsetMin", "offsetMax", "anchorMin", "anchorMax", "pivot",
                        })
                    )
                    if (match.group(2) == "+=" and key[0] not in scalars and not value_member
                            and key not in subscriptions[method.class_identity]):
                        add("EVENT_NO_UNSUBSCRIBE", match.start())
            ordered = sorted(hot, key=lambda context: (-context[1], len(context[2]), context[0], context[2]))
            root, frequency, via = ordered[0] if ordered else (None, 1, ())
            for (rule, line), offsets in sorted(sites.items(), key=lambda item: (item[0][1], item[0][0])):
                finding = {"rule": rule, "file": source.file, "line": line,
                           "line_text": lines[line - 1].strip(), "method": method.qualified,
                           "hot_method": root, "via": list(via), "sites": len(offsets),
                           "frequency": frequency, "score": len(offsets) * frequency}
                finding["key"] = baseline_key(finding)
                findings.append(finding)
    return sorted(findings, key=lambda finding: (finding["file"], finding["line"], finding["rule"]))


def project_sources(project, include_tests=False):
    assets = project / "Assets"
    if not project.is_dir():
        raise ValueError("--project must be an existing directory")
    if not assets.is_dir():
        # Standalone script folders (including scanner fixtures) need no Unity
        # project scaffold. A Unity project's Assets remains the exclusive root.
        if not any(project.glob("*.cs")):
            raise ValueError("--project must contain Assets or C# scripts")
        assets = project
    sources = []
    for path in sorted(assets.rglob("*.cs")):
        relative = path.relative_to(project)
        if any(part in {"Library", "Packages", "Temp"} for part in relative.parts[:-1]):
            continue
        if not include_tests and any("tests" in part.lower() for part in relative.parts[:-1]):
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(project.resolve()):
            continue
        sources.append(parse_source(relative.as_posix(), path.read_text(encoding="utf-8-sig")))
    return sources


def read_baseline(path):
    if not path.exists():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("findings"), dict):
        raise ValueError("baseline must contain version: 1 and a findings object keyed by rule/file/source text")
    if not all(isinstance(key, str) and isinstance(value, dict) for key, value in data["findings"].items()):
        raise ValueError("invalid baseline finding")
    return set(data["findings"])


def write_baseline(path, findings):
    data = {"version": 1, "findings": {finding["key"]: {
        "rule": finding["rule"], "file": finding["file"],
        "line_text": normalized_line(finding["line_text"]),
    } for finding in findings}}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def make_report(findings, known):
    totals = defaultdict(int)
    for finding in findings:
        finding["is_new"] = finding["key"] not in known
        totals[finding["file"]] += finding["score"]
    new = sum(finding["is_new"] for finding in findings)
    result = "RESULT: FAIL {} new".format(new) if new else "RESULT: OK {} findings (0 new)".format(len(findings))
    return {"version": 1, "findings": findings, "total": len(findings), "new": new,
            "top_files": [{"file": file, "score": score} for file, score in
                          sorted(totals.items(), key=lambda item: (-item[1], item[0]))],
            "result": result}


def render_text(report, markdown=False):
    output, previous = [], None
    for finding in report["findings"]:
        if finding["file"] != previous:
            output.extend(["", ("### " if markdown else "") + finding["file"]])
            previous = finding["file"]
        context = finding["hot_method"] or finding["method"]
        if finding["via"]:
            context += " via " + " -> ".join(finding["via"])
        output.append("{}{}:{} {} [{}; score={}]{}".format(
            "- " if markdown else "  ", finding["line"], finding["rule"],
            finding["method"], context, finding["score"], " NEW" if finding["is_new"] else ""))
    if not report["findings"]:
        output.append("No findings.")
    output.extend(["", "Top files by estimated site-frequency score", "", "File | Score", "--- | ---"])
    output.extend("{} | {}".format(item["file"], item["score"]) for item in report["top_files"])
    output.extend(["", report["result"]])
    return "\n".join(output).lstrip() + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", type=Path, default=Path("."))
    parser.add_argument("--changed", nargs="+", metavar="FILE", help="report only these project-relative or absolute paths")
    parser.add_argument("--include-tests", action="store_true", help="include folders whose names contain Tests")
    parser.add_argument("--baseline", type=Path, metavar="FILE")
    parser.add_argument("--update-baseline", action="store_true", help="accept current full-project findings; requires --baseline")
    formats = parser.add_mutually_exclusive_group()
    formats.add_argument("--json", action="store_true", help="JSON stdout; RESULT footer on stderr")
    formats.add_argument("--md", nargs="?", const="-", metavar="FILE", help="Markdown to stdout, or optionally FILE")
    args = parser.parse_args(argv)
    if args.update_baseline and args.baseline is None:
        parser.error("--update-baseline requires --baseline FILE")
    try:
        project = args.project.resolve()
        known = read_baseline(args.baseline) if args.baseline else set()
        findings = scan_sources(project_sources(project, args.include_tests))
        selected = None
        if args.changed:
            selected = set()
            for name in args.changed:
                path = Path(name)
                path = path if path.is_absolute() else project / path
                selected.add(path.resolve().relative_to(project).as_posix())
        if args.update_baseline:
            write_baseline(args.baseline, findings)
            known = {finding["key"] for finding in findings}
        report = make_report([finding for finding in findings if selected is None or finding["file"] in selected], known)
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
            print(report["result"], file=sys.stderr)
        elif args.md and args.md != "-":
            Path(args.md).write_text(render_text(report, markdown=True), encoding="utf-8")
            print(report["result"])
        else:
            print(render_text(report, markdown=bool(args.md)), end="")
        return 1 if report["new"] else 0
    except (OSError, ValueError) as error:
        print("ERROR: {}".format(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
