import json

import pytest
from pydantic import ValidationError

from gamedevworkstation.features.pi_contracts import (
    Answer, EvalResult, Fact, ImproverOutcome, PiFormatError, ProjectFacts, parse_eval)


def q(i="q1", n=2, topic="target", rec="o1"):
    return {"id": i, "topic": topic, "text": "Which scene?", "recommended": rec, "rationale": "cheapest",
            "options": [{"id": f"o{k + 1}", "label": f"Option {k + 1}"} for k in range(n)]}


def result(decision="ASK", questions=None):
    return {"decision": decision, "questions": [q()] if questions is None else questions, "task_card": {"goal": "Add double jump"}}


def test_parse_eval_happy_path_and_fence():
    r = parse_eval(json.dumps(result()))
    assert r.decision == "ASK" and r.questions[0].options[1].id == "o2" and r.task_card.goal == "Add double jump"
    fenced = "```json\n" + json.dumps(result("PROCEED", [])) + "\n```"
    assert parse_eval(fenced).decision == "PROCEED"


@pytest.mark.parametrize("text", ["", "   ", "not json", "[1, 2]", "{broken", "```json\n```"])
def test_parse_eval_rejects_non_json(text):
    with pytest.raises(PiFormatError):
        parse_eval(text)


def test_parse_eval_more_than_three_questions():
    qs = [q(f"q{i}") for i in range(4)]
    with pytest.raises(PiFormatError):
        parse_eval(json.dumps(result(questions=qs)))


@pytest.mark.parametrize("n", [1, 5])
def test_parse_eval_wrong_option_count(n):
    with pytest.raises(PiFormatError):
        parse_eval(json.dumps(result(questions=[q(n=n)])))


def test_parse_eval_unknown_topic_and_bad_recommended():
    with pytest.raises(PiFormatError):
        parse_eval(json.dumps(result(questions=[q(topic="graphics")])))
    with pytest.raises(PiFormatError):
        parse_eval(json.dumps(result(questions=[q(rec="zzz")])))


def test_parse_eval_decision_question_consistency_and_duplicates():
    with pytest.raises(PiFormatError):
        parse_eval(json.dumps(result("PROCEED", [q()])))
    with pytest.raises(PiFormatError):
        parse_eval(json.dumps(result("ASK", [])))
    with pytest.raises(PiFormatError):
        parse_eval(json.dumps(result(questions=[q("a"), q("a")])))


def test_parse_eval_extra_fields_forbidden():
    d = result()
    d["surprise"] = 1
    with pytest.raises(PiFormatError):
        parse_eval(json.dumps(d))


def test_fact_rules():
    assert Fact(value="unknown", source="Assets/x").source == "unknown"
    with pytest.raises(ValidationError):
        Fact(value="x", source="/etc/passwd")
    with pytest.raises(ValidationError):
        Fact(value="x", source="a/../b")
    with pytest.raises(ValidationError):
        Fact(value="x" * 401)
    assert Fact(value=" padded ").value == "padded"


def test_project_facts_defaults_are_unknown():
    f = ProjectFacts(project="/p")
    assert f.unity_version.value == f.render_pipeline.value == f.input_handler.value == "unknown"


def test_answer_rules():
    assert Answer(question_id="q1", skipped=True).skipped
    with pytest.raises(ValidationError):
        Answer(question_id="q1", skipped=True, option_id="o1")
    with pytest.raises(ValidationError):
        Answer(question_id="q1")
    assert Answer(question_id="q1", free_text="custom").free_text == "custom"


def test_improver_outcome_context_cap():
    ImproverOutcome(status="proceeded", context_text="x" * 6000)
    with pytest.raises(ValidationError):
        ImproverOutcome(status="proceeded", context_text="x" * 6001)
    with pytest.raises(ValidationError):
        ImproverOutcome(status="nope")


def test_eval_result_roundtrip():
    r = EvalResult.model_validate(result())
    assert EvalResult.model_validate(r.model_dump()) == r


def test_outcome_text_fields_keep_their_spaces():
    o = ImproverOutcome(status="bypassed", execution_text="  keep me  ", context_text=" ctx ")
    assert o.execution_text == "  keep me  " and o.context_text == " ctx "
    assert ImproverOutcome(status="unavailable", failure_item_id="it_1").failure_item_id == "it_1"


def test_ask_may_omit_the_card_but_proceed_may_not():
    r = parse_eval(json.dumps({"decision": "ASK", "questions": [q()]}))
    assert r.task_card is None
    with pytest.raises(PiFormatError):
        parse_eval(json.dumps({"decision": "PROCEED", "questions": []}))


def test_object_cited_facts_become_strings_and_are_capped():
    data = result("PROCEED", [])
    data["cited_facts"] = [{"source": "project_facts", "fact": "unity_version: 6000.0.23f1"}, "Assets/A.cs", 7, None,
                           {"nested": {"x": 1}}] + [f"f{i}" for i in range(30)]
    facts = parse_eval(json.dumps(data)).cited_facts
    assert facts[:3] == ["project_facts: unity_version: 6000.0.23f1", "Assets/A.cs", "7"] and len(facts) == 20


def test_a_question_with_an_invented_topic_is_dropped_but_all_invented_fails():
    data = result("ASK", [q("q1"), q("q2", topic="scope")])
    assert [x.id for x in parse_eval(json.dumps(data)).questions] == ["q1"]
    with pytest.raises(PiFormatError):
        parse_eval(json.dumps(result("ASK", [q("q1", topic="scope")])))
