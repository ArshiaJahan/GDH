"""Task board: Task00001 codes (sequential, never reused, concurrency-safe), code parsing, the
task_* tools (subtask ops all or nothing, Plan only mode, subagents), search filters, events and
the REST API (next to the scheduled tasks under /api/tasks)."""
import asyncio
import datetime as dt
import threading

import pytest
from fastapi.testclient import TestClient

from workspace.agent.tools import ToolContext
from workspace.app import AppState
from workspace.db import DB, SCHEMA_VERSION
from workspace.features import task_board as TB
from workspace.providers.fake import FakeProvider
from workspace.server import create_app

H = {"Authorization": "Bearer t"}
WRITE_TOOLS = {"task_create", "task_update", "task_comment", "task_archive", "task_restore"}
READ_TOOLS = {"task_boards", "task_search", "task_get"}


@pytest.fixture
def app(tmp_path):
    a = AppState(db_path=tmp_path / "b.db")
    a.tb = TB.install(a)
    return a


@pytest.fixture
def env(tmp_path):
    s = AppState(db_path=tmp_path / "t.db")
    s.providers.override("anthropic", "default", FakeProvider())
    with TestClient(create_app("t", s)) as c:
        yield c, s


def ctx_for(app, s, role="main"):
    return ToolContext(app=app, session=s, run_id=f"main:{s['id']}", role=role)


def day(n: int) -> str:
    return (dt.date.today() + dt.timedelta(days=n)).isoformat()


# ------------------------------------------------------------------ codes


@pytest.mark.parametrize("ref,num", [("Task00001", 1), ("task00001", 1), ("TASK00001", 1), ("task1", 1), ("1", 1),
                                     ("00001", 1), ("#1", 1), ("#Task00001", 1), (" Task-7 ", 7), ("task 12", 12),
                                     (42, 42), ("Task123456", 123456)])
def test_parse_code_variants(ref, num):
    assert TB.parse_code(ref) == num


@pytest.mark.parametrize("ref", ["", None, "0", "Task00000", "abc", "Task", "#", "Task1x", -3, True, "1.5"])
def test_parse_code_rejects(ref):
    assert TB.parse_code(ref) is None


def test_format_and_mentions():
    assert TB.format_code(1) == "Task00001" and TB.format_code(99999) == "Task99999"
    assert TB.format_code(100000) == "Task100000"  # grows past five digits
    text = "See Task00012 and task00003, Task00012 again; not MyTask00004, Task12 or Task000001x"
    assert TB.mentioned_codes(text) == ["Task00012", "Task00003"]


def test_migration_and_default_board(app, tmp_path):
    assert app.db.user_version() == SCHEMA_VERSION >= 4
    b = app.tb.boards()
    assert [x["name"] for x in b] == ["Game"]
    assert [(c["name"], c["is_done"]) for c in b[0]["columns"]] == [
        ("Backlog", False), ("To do", False), ("In progress", False), ("Review", False), ("Done", True)]
    assert app.db.one("SELECT next FROM task_counter")["next"] == 1
    DB(tmp_path / "b.db").close()  # reopening doesn't seed again
    assert len(AppState(db_path=tmp_path / "b.db").db.all("SELECT * FROM task_boards")) == 1


def test_codes_are_sequential_and_never_reused(app, tmp_path):
    tb = app.tb
    codes = [tb.create(title=f"T{i}")["code"] for i in range(3)]
    assert codes == ["Task00001", "Task00002", "Task00003"]
    tb.archive("Task00003")
    assert tb.create(title="after archive")["code"] == "Task00004"
    tb.archive(4)
    tb.delete("task4")  # deleted for good: the number stays used
    tb.delete(tb.archive("Task00003")["code"])
    assert tb.create(title="after delete")["code"] == "Task00005"
    # A fresh process on the same database continues the counter, even with the top task gone.
    tb.delete(tb.archive(5)["code"])
    app2 = AppState(db_path=tmp_path / "b.db")
    assert TB.install(app2).create(title="reopened")["code"] == "Task00006"
    with pytest.raises(TB.NotFound):
        tb.get("Task00004")


def test_code_allocation_is_concurrency_safe(app, tmp_path):
    other = TB.install(AppState(db_path=tmp_path / "b.db"))  # a second connection to the same file
    got: list[int] = []
    errors: list[Exception] = []
    lock = threading.Lock()

    def worker(tb, n):
        try:
            for i in range(n):
                d = tb.create(title=f"t{i}")
                with lock:
                    got.append(d["num"])
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(app.tb if i % 2 else other, 10)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert sorted(got) == list(range(1, 81))
    assert app.db.one("SELECT next FROM task_counter")["next"] == 81


def test_lookup_accepts_every_form(app):
    d = app.tb.create(title="One")
    for ref in ("Task00001", "task00001", "TASK1", "1", "00001", "#1", 1, d["id"]):
        assert app.tb.get(ref)["id"] == d["id"]
    with pytest.raises(TB.NotFound):
        app.tb.get("Task00099")


# ------------------------------------------------------------------ tools


async def test_tools_create_update_comment_and_link(app):
    s = app.store.create(title="Work")
    ctx = ctx_for(app, s)
    q = app.bus.subscribe()
    out = await app.tools.run(ctx, "task_create", {"title": "Fix jump buffer", "labels": ["#player", "input"],
                                                    "priority": "high", "assignees": ["me", "Claude"],
                                                    "due": day(2), "column": "todo"})
    assert not out.is_error and "Task00001" in out.text and "To do" in out.text
    d = app.tb.get("Task00001")
    assert d["agent_touched"] and d["created_by"] == "agent" and d["labels"] == ["player", "input"]
    assert d["assignees"] == ["me", "agent"] and [x["id"] for x in d["linked_sessions"]] == [s["id"]]
    assert [t["code"] for t in app.tb.by_session(s["id"])] == ["Task00001"]

    app.tb.create(title="Second", column="In progress")
    out = await app.tools.run(ctx, "task_update", {"task": "1", "column": "In progress", "position": "top",
                                                    "add_assignees": ["Sam"], "remove_assignees": ["me"], "due": ""})
    assert not out.is_error and "moved to In progress" in out.text and "Task00001" in out.text
    d = app.tb.get(1)
    assert d["column"] == "In progress" and d["position"] == 0 and d["due"] is None and d["assignees"] == ["agent", "Sam"]
    assert app.tb.get(2)["position"] == 1
    out = await app.tools.run(ctx, "task_update", {"task": "Task00001", "column": "Nowhere"})
    assert out.is_error and "No column" in out.text and "Backlog" in out.text

    out = await app.tools.run(ctx, "task_comment", {"task": "task1", "body": "Looks like **coyote time**."})
    assert not out.is_error
    c = app.tb.get(1)["comments_list"][0]
    assert c["author"] == "agent" and c["by_agent"] and c["session_id"] == s["id"]
    acts = app.tb.get(1)["activity"]
    assert acts[0]["action"] == "commented" and all(a["actor"] == "agent" for a in acts)

    out = await app.tools.run(ctx, "task_get", {"task": "#1"})
    assert "Task00001: Fix jump buffer" in out.text and "coyote time" in out.text and "Work" in out.text
    out = await app.tools.run(ctx, "task_boards", {})
    assert "Game" in out.text and "In progress: 2" in out.text and "Sam" in out.text

    out = await app.tools.run(ctx, "task_archive", {"task": "Task00001"})
    assert "Recently deleted" in out.text and app.tb.get(1)["archived"]
    out = await app.tools.run(ctx, "task_search", {"archived": True})
    assert "Task00001" in out.text
    out = await app.tools.run(ctx, "task_restore", {"task": "Task00001"})
    assert not out.is_error and not app.tb.get(1)["archived"]

    types = [e["type"] for e in list(q.items) if e["type"].startswith("task.")]
    assert types == ["task.created", "task.created", "task.updated", "task.updated", "task.archived", "task.restored"]
    ev = next(e for e in q.items if e["type"] == "task.created")
    assert ev["data"]["task"]["code"] == "Task00001" and ev["data"]["actor"] == "agent" and ev["seq"]


async def test_subtask_ops_are_all_or_nothing(app):
    s = app.store.create(title="Work")
    ctx = ctx_for(app, s)
    app.tb.create(title="Level 1")
    out = await app.tools.run(ctx, "task_update", {"task": "1", "subtasks": [
        {"op": "add", "title": "Greybox"}, {"op": "add", "title": "Lighting"}]})
    assert not out.is_error and "Greybox" in out.text
    subs = app.tb.get(1)["subtasks_list"]
    g, li = subs[0]["id"], subs[1]["id"]
    assert g in out.text  # new ids come back for the next ops
    out = await app.tools.run(ctx, "task_update", {"task": "1", "subtasks": [
        {"op": "add_item", "subtaskId": g, "title": "Walls"}, {"op": "add_item", "subtaskId": g, "title": "Doors"},
        {"op": "toggle", "id": li, "done": True}, {"op": "move", "id": li, "index": 0},
        {"op": "add", "title": "Audio", "after": li}, {"op": "rename", "id": g, "title": "Blockout"}]})
    assert not out.is_error
    before = app.tb.get(1)["subtasks_list"]
    assert [x["title"] for x in before] == ["Lighting", "Audio", "Blockout"]
    assert before[0]["done"] and [i["title"] for i in before[2]["items"]] == ["Walls", "Doors"]
    item = before[2]["items"][1]["id"]

    # One bad op in the middle: nothing of the batch is saved.
    out = await app.tools.run(ctx, "task_update", {"task": "1", "title": "Renamed", "subtasks": [
        {"op": "toggle_item", "subtaskId": g, "id": item}, {"op": "remove", "id": "st_missing"},
        {"op": "add", "title": "Never"}]})
    assert out.is_error and "Op 2" in out.text and "st_missing" in out.text
    d = app.tb.get(1)
    assert d["subtasks_list"] == before and d["title"] == "Level 1"
    for bad in ([{"op": "explode"}], [{"op": "add", "title": "  "}], [{"op": "add_item", "subtaskId": g, "title": "x" * 301}],
                [{"op": "move_item", "subtaskId": li, "id": item, "index": 0}]):
        out = await app.tools.run(ctx, "task_update", {"task": "1", "subtasks": bad})
        assert out.is_error, bad
    assert app.tb.get(1)["subtasks_list"] == before

    out = await app.tools.run(ctx, "task_update", {"task": "1", "subtasks": [
        {"op": "toggle_item", "subtaskId": g, "id": item}, {"op": "move_item", "subtaskId": g, "id": item, "index": 0},
        {"op": "rename_item", "subtaskId": g, "id": item, "title": "Door frames"}, {"op": "toggle", "id": g}]})
    assert not out.is_error
    d = app.tb.get(1)
    blk = d["subtasks_list"][2]
    assert blk["done"] and blk["items"][0] == {"id": item, "title": "Door frames", "done": True}
    assert d["subtasks"] == {"done": 2, "total": 3}
    out = await app.tools.run(ctx, "task_update", {"task": "1", "subtasks": [
        {"op": "remove_item", "subtaskId": g, "id": item}, {"op": "remove", "id": li}]})
    assert not out.is_error and [x["title"] for x in app.tb.get(1)["subtasks_list"]] == ["Audio", "Blockout"]
    with pytest.raises(TB.TaskError):
        TB.apply_subtask_ops([], [{"op": "add", "title": "x"}] * (TB.MAX_OPS + 1))


async def test_plan_mode_and_subagents_only_read(app):
    s = app.store.create(title="Plan", mode="plan")
    ctx = ctx_for(app, s)
    app.tb.create(title="Existing")
    for name, args in [("task_create", {"title": "Nope"}), ("task_update", {"task": "1", "title": "x"}),
                       ("task_comment", {"task": "1", "body": "x"}), ("task_archive", {"task": "1"}),
                       ("task_restore", {"task": "1"})]:
        out = await app.tools.run(ctx, name, args)
        assert out.is_error and "Plan only" in out.text, name
    d = app.tb.get(1)
    assert d["title"] == "Existing" and not d["comments_list"] and not d["archived"]
    assert app.db.one("SELECT COUNT(*) AS n FROM board_tasks")["n"] == 1
    out = await app.tools.run(ctx, "task_search", {"query": "exist"})
    assert not out.is_error and "Task00001" in out.text

    # Subagents can be given the read tools, never the write tools.
    sub_specs = {t.name for t in app.tools.specs(list(READ_TOOLS | WRITE_TOOLS), role="subagent", session=s)}
    assert READ_TOOLS <= sub_specs and not (WRITE_TOOLS & sub_specs)
    sub = ctx_for(app, {**s, "mode": "accept_edits"}, role="subagent")
    out = await app.tools.run(sub, "task_create", {"title": "x"}, allowed=list(WRITE_TOOLS))
    assert out.is_error and "not available" in out.text
    out = await app.tools.run(sub, "task_get", {"task": "1"}, allowed=["task_get"])
    assert not out.is_error and "Existing" in out.text
    assert all(app.tools.tools[n].spec.read_only for n in READ_TOOLS)
    assert not any(app.tools.tools[n].spec.read_only for n in WRITE_TOOLS)


def test_tools_offered_and_prompt_note(app):
    s = app.store.create(title="On")
    names = {t.name for t in app.runner.tool_specs(s)}
    assert READ_TOOLS | WRITE_TOOLS <= names
    seg = app.runner.system_segments(s)
    assert TB.PROMPT_NOTE in seg[-1] and app.runner.system_segments(s) == seg  # in the session segment, stable
    off = app.store.create(title="Off", task_board=False)
    assert not ({t.name for t in app.runner.tool_specs(off)} & (READ_TOOLS | WRITE_TOOLS))
    assert all(TB.PROMPT_NOTE not in x for x in app.runner.system_segments(off))
    assert len(TB.PROMPT_NOTE) < 250  # keep the note light


async def test_tool_errors_are_readable(app):
    ctx = ctx_for(app, app.store.create(title="x"))
    for name, args, msg in [("task_get", {"task": "Task00042"}, "No task"),
                            ("task_create", {"title": " "}, "empty"),
                            ("task_create", {"title": "x", "priority": "asap"}, "Priority"),
                            ("task_create", {"title": "x", "due": "next week"}, "Due date"),
                            ("task_create", {"title": "x", "board": "Nope"}, "No board"),
                            ("task_update", {"task": "1", "colour": "red"}, "No task"),
                            ("task_search", {"due": "soon"}, "Due filter")]:
        out = await app.tools.run(ctx, name, args)
        assert out.is_error and msg in out.text, (name, out.text)
    app.tb.create(title="x")
    out = await app.tools.run(ctx, "task_update", {"task": "1", "colour": "red"})
    assert out.is_error and "Unknown field" in out.text


# ------------------------------------------------------------------ search


def test_search_filters(app):
    tb = app.tb
    tb.create(title="Overdue jump bug", due=day(-1), priority="urgent", labels=["bug"], assignees=["me"])
    tb.create(title="Due today", due=day(0), assignees=["agent"], description="Coyote time tweak")
    tb.create(title="Soon", due=day(3), labels=["Polish"])
    tb.create(title="Later", due=day(10))
    tb.create(title="No date at all")
    tb.create(title="Finished but late", due=day(-5), column="Done")
    b2 = tb.create_board("Art", columns=["Ideas", "Shipped"])
    tb.update_column(b2["columns"][1]["id"], is_done=True)
    tb.create(title="Concept jump pose", board="Art", column="Ideas", labels=["bug"])

    def codes(**kw):
        return [t["code"] for t in tb.search(**kw)[0]]

    assert codes(due="overdue") == ["Task00001"]  # the done one isn't overdue
    assert codes(due="today") == ["Task00002"]
    assert codes(due="week") == ["Task00002", "Task00003"]
    assert codes(due="none") == ["Task00005", "Task00007"]
    assert codes(assignee="me") == ["Task00001"] and codes(assignee="Agent") == ["Task00002"]
    assert codes(assignee="unassigned") == ["Task00003", "Task00004", "Task00005", "Task00007"]
    assert codes(label="#BUG") == ["Task00001", "Task00007"] and codes(label="polish") == ["Task00003"]
    assert codes(priority="urgent") == ["Task00001"]
    assert codes(query="jump") == ["Task00001", "Task00007"]
    assert codes(query="coyote tweak") == ["Task00002"]  # every word, in the description
    assert codes(query="Task00004") == ["Task00004"] and codes(query="#4") == ["Task00004"]
    assert codes(query="100%") == []  # LIKE wildcards are literal
    assert codes(query="finished") == []  # done columns are left out…
    assert codes(query="finished", include_done=True) == ["Task00006"]  # …unless include_done
    assert codes(column="Done") == ["Task00006"]  # or the search names the done column
    assert codes(board="art") == ["Task00007"] and codes(board="Game", column="backlog")[:2] == ["Task00001", "Task00002"]
    assert codes(column="Ideas") == ["Task00007"]
    with pytest.raises(TB.NotFound):
        tb.search(column="Nowhere")
    tb.archive(3)
    assert "Task00003" not in codes(include_done=True)
    assert codes(archived=True) == ["Task00003"]
    rows, total = tb.search(limit=2)
    assert len(rows) == 2 and total == 5
    sug = [x["code"] for x in tb.suggest("Task0000")]
    assert sug[0] == "Task00007" and "Task00003" not in sug
    assert [x["code"] for x in tb.suggest("4")][0] == "Task00004"
    assert [x["code"] for x in tb.suggest("pose")] == ["Task00007"]
    assert [x["code"] for x in tb.suggest("Ta")][:2] == ["Task00007", "Task00006"]  # the start of a code


def test_columns_and_boards(app):
    tb = app.tb
    g = tb.board()
    tb.create(title="a", column="Review")
    tb.create(title="b", column="Review")
    col = tb.add_column(g["id"], "QA", index=4)
    assert [c["name"] for c in tb.board("game")["columns"]] == ["Backlog", "To do", "In progress", "Review", "QA", "Done"]
    tb.update_column(col["id"], name="Playtest")
    ids = [c["id"] for c in tb.board()["columns"]]
    tb.reorder_columns(g["id"], [ids[-1], *ids[:-1]])
    assert tb.board()["columns"][0]["name"] == "Done"
    with pytest.raises(TB.TaskError):
        tb.reorder_columns(g["id"], ids[:-1])
    with pytest.raises(TB.TaskError):
        tb.add_column(g["id"], "playtest")  # names are unique per board
    review = tb.column(tb.board(), "review")["id"]
    tb.delete_column(review, move_to="Playtest")
    assert {tb.get(1)["column"], tb.get(2)["column"]} == {"Playtest"}
    assert "Review" not in [c["name"] for c in tb.board()["columns"]]
    with pytest.raises(TB.TaskError):
        tb.delete_board(g["id"])  # the only board
    art = tb.create_board("Art")
    tb.update(1, {"board": "Art"})
    assert tb.get(1)["board"] == "Art" and tb.get(1)["column"] == "Backlog"
    with pytest.raises(TB.TaskError):
        tb.delete_board(art["id"])  # still has a task
    tb.delete_board(art["id"], force=True)
    assert [b["name"] for b in tb.boards()] == ["Game"]
    with pytest.raises(TB.NotFound):
        tb.get(1)
    assert tb.create(title="c")["code"] == "Task00003"


def test_complete_and_positions(app):
    tb = app.tb
    for t in "abc":
        tb.create(title=t, column="To do")
    tb.update(3, {"index": 0})
    assert [t["code"] for t in tb.search(column="To do")[0]] == ["Task00003", "Task00001", "Task00002"]
    tb.update(1, {"column": "Backlog", "index": 0})
    tb.update(2, {"column": "Backlog", "index": 0})  # index 0 is the top, not "no position"
    assert [t["code"] for t in tb.search(column="Backlog")[0]] == ["Task00002", "Task00001"]
    d = tb.complete("Task00002")
    assert d["column"] == "Done" and d["done"]
    assert tb.complete(2)["column"] == "Done"  # already done: no change


# ------------------------------------------------------------------ REST


def test_rest_api(env):
    c, s = env
    boards = c.get("/api/tasks/boards", headers=H).json()
    assert boards["boards"][0]["name"] == "Game" and "me" in boards["people"]
    t = c.post("/api/tasks/items", json={"title": "Main menu", "labels": ["ui"], "priority": "medium",
                                         "column": "To do"}, headers=H).json()
    assert t["code"] == "Task00001" and t["column"] == "To do" and not t["agent_touched"] and t["created_by"] == "me"
    assert c.get("/api/tasks/by-code/1", headers=H).json()["id"] == t["id"]
    assert c.get("/api/tasks/items/task00001", headers=H).json()["title"] == "Main menu"
    assert c.get("/api/tasks/items/Task00077", headers=H).status_code == 404
    assert c.post("/api/tasks/items", json={"title": ""}, headers=H).status_code == 400

    r = c.patch("/api/tasks/items/Task00001", json={"column": "In progress", "due": day(1), "assignees": ["Me", "Ana"]},
                headers=H).json()
    assert r["column"] == "In progress" and r["due"] == day(1) and r["assignees"] == ["me", "Ana"]
    assert r["activity"][0]["actor"] == "me"
    r = c.post("/api/tasks/items/1/subtasks", json={"ops": [{"op": "add", "title": "Buttons"}]}, headers=H).json()
    assert r["subtasks_list"][0]["title"] == "Buttons"
    bad = c.post("/api/tasks/items/1/subtasks", json={"ops": [{"op": "add", "title": "x"}, {"op": "remove", "id": "zz"}]},
                 headers=H)
    assert bad.status_code == 400 and "Op 2" in bad.json()["detail"]
    assert len(c.get("/api/tasks/items/1", headers=H).json()["subtasks_list"]) == 1
    r = c.post("/api/tasks/items/1/comments", json={"body": "Use the new font"}, headers=H).json()
    assert r["comments_list"][0]["author"] == "me" and not r["comments_list"][0]["by_agent"]

    found = c.get("/api/tasks/search", params={"q": "menu", "label": "ui", "due": "week"}, headers=H).json()
    assert [x["code"] for x in found["tasks"]] == ["Task00001"] and found["total"] == 1
    assert c.get("/api/tasks/search", params={"due": "later"}, headers=H).status_code == 400
    assert c.get("/api/tasks/suggest", params={"q": "task"}, headers=H).json()[0]["code"] == "Task00001"
    assert c.post("/api/tasks/items/1/done", headers=H).json()["column"] == "Done"

    # Sessions: link, attach to the chat context, unlink.
    sid = c.post("/api/sessions", json={}, headers=H).json()["id"]
    assert c.post("/api/tasks/items/1/sessions", json={"session_id": "nope"}, headers=H).status_code == 404
    r = c.post("/api/tasks/items/1/attach", json={"session_id": sid}, headers=H).json()
    assert [x["id"] for x in r["linked_sessions"]] == [sid]
    assert [x["code"] for x in c.get(f"/api/tasks/by-session/{sid}", headers=H).json()] == ["Task00001"]
    msgs = s.store.messages(sid)
    assert msgs[-1].meta["task_context"] == "Task00001" and "Main menu" in msgs[-1].text()
    assert "Use the new font" in msgs[-1].text()
    r = c.delete(f"/api/tasks/items/1/sessions/{sid}", headers=H).json()
    assert r["linked_sessions"] == []

    # Archive, restore, delete for good; the code isn't handed out again.
    assert c.delete("/api/tasks/items/1", headers=H).status_code == 400  # only from Recently deleted
    assert c.post("/api/tasks/items/1/archive", headers=H).json()["archived"]
    assert [x["code"] for x in c.get("/api/tasks/archived", headers=H).json()["tasks"]] == ["Task00001"]
    assert not c.post("/api/tasks/items/1/restore", headers=H).json()["archived"]
    c.post("/api/tasks/items/1/archive", headers=H)
    assert c.delete("/api/tasks/items/Task00001", headers=H).json()["code"] == "Task00001"
    assert c.post("/api/tasks/items", json={"title": "Next"}, headers=H).json()["code"] == "Task00002"

    # Boards and columns.
    b = c.post("/api/tasks/boards", json={"name": "Audio"}, headers=H).json()
    assert [x["name"] for x in b["columns"]][-1] == "Done"
    assert c.post("/api/tasks/boards", json={"name": "audio"}, headers=H).status_code == 400
    col = c.post(f"/api/tasks/boards/{b['id']}/columns", json={"name": "Mixing", "index": 1}, headers=H).json()
    assert c.patch(f"/api/tasks/columns/{col['id']}", json={"name": "Mix"}, headers=H).json()["name"] == "Mix"
    order = [x["id"] for x in c.get("/api/tasks/boards", headers=H).json()["boards"][1]["columns"]][::-1]
    assert c.post(f"/api/tasks/boards/{b['id']}/order", json={"column_ids": order}, headers=H).json()["columns"][0]["name"] == "Done"
    assert c.delete(f"/api/tasks/columns/{col['id']}", headers=H).json()["ok"]
    assert c.patch(f"/api/tasks/boards/{b['id']}", json={"name": "Sound"}, headers=H).json()["name"] == "Sound"
    assert c.delete(f"/api/tasks/boards/{b['id']}", headers=H).json()["ok"]

    # The scheduled tasks keep their routes next to the board's.
    sched = c.post("/api/tasks", json={"name": "n", "prompt": "p", "schedule": "0 9 * * *"}, headers=H)
    assert sched.status_code == 200 and c.get("/api/tasks", headers=H).json()["tasks"][0]["name"] == "n"
    assert c.patch(f"/api/tasks/{sched.json()['id']}", json={"enabled": False}, headers=H).status_code == 200


def test_attach_refused_while_running(env):
    c, s = env
    c.post("/api/tasks/items", json={"title": "x"}, headers=H)
    sid = c.post("/api/sessions", json={}, headers=H).json()["id"]

    class Busy:
        def done(self):
            return False

    s.runner.running[sid] = Busy()  # type: ignore[assignment]
    try:
        r = c.post("/api/tasks/items/1/attach", json={"session_id": sid}, headers=H)
        assert r.status_code == 400 and "working" in r.json()["detail"]
    finally:
        s.runner.running.pop(sid, None)


async def test_agent_turn_uses_the_board(tmp_path):
    """A whole main-agent turn: the model calls task_create and the board shows the task."""
    from workspace.providers.fake import text_response, tool_response

    app = AppState(db_path=tmp_path / "turn.db")
    TB.install(app)
    fake = FakeProvider()
    fake.script = [tool_response("task_create", {"title": "Write the GDD", "column": "To do"}), text_response("Added Task00001.")]
    app.providers.override("anthropic", "default", fake)
    s = app.store.create(title="Plan the game")
    from workspace.core.types import Message

    app.store.add_message(s["id"], Message.user("Put 'Write the GDD' on the board"))
    await app.runner.start(s["id"])
    t = app.extensions["task_board"].get("Task00001")
    assert t["title"] == "Write the GDD" and t["agent_touched"] and t["linked_sessions"][0]["id"] == s["id"]
    assert any(TB.PROMPT_NOTE in seg for seg in fake.calls[0].system)
    await asyncio.sleep(0)
