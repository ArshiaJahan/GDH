"""Review Desk: LLM vs human agreement (drafted by GLM Flash, checked by hand)."""
from gamedevworkstation.features.review_agreement import agreement, pair_up


def rv(verdict, c, m, t, fm="none"):
    return {
        "verdict": verdict,
        "scores": {"correctness": c, "maintainability": m, "test_quality": t},
        "failure_mode": fm,
    }


def test_perfect_agreement():
    pairs = [(rv("accept", 5, 4, 5, "none"), rv("accept", 5, 4, 5, "none"))]
    r = agreement(pairs)
    assert r["n"] == 1
    assert r["verdict_agreement"] == 1.0
    assert r["kappa"] == 1.0
    assert r["score_mae"] == {
        "correctness": 0.0,
        "maintainability": 0.0,
        "test_quality": 0.0,
        "overall": 0.0,
    }
    assert r["within_one"] == 1.0
    assert r["failure_mode_agreement"] == 1.0
    assert r["confusion"] == {
        "accept/accept": 1,
        "accept/reject": 0,
        "reject/accept": 0,
        "reject/reject": 0,
    }


def test_total_disagreement():
    pairs = [
        (rv("accept", 5, 5, 5), rv("reject", 1, 1, 1)),
        (rv("reject", 2, 2, 2), rv("accept", 4, 4, 4)),
    ]
    r = agreement(pairs)
    assert r["n"] == 2
    assert r["verdict_agreement"] == 0.0
    assert r["kappa"] == -1.0
    # diffs: 4,4,4 and 2,2,2 -> overall (4+4+4+2+2+2)/6 = 3.0
    assert r["score_mae"] == {
        "correctness": 3.0,
        "maintainability": 3.0,
        "test_quality": 3.0,
        "overall": 3.0,
    }
    assert r["within_one"] == 0.0
    assert r["failure_mode_agreement"] == 1.0
    assert r["confusion"] == {
        "accept/accept": 0,
        "accept/reject": 1,
        "reject/accept": 1,
        "reject/reject": 0,
    }


def test_kappa_hand_computed():
    # pairs: (A,A),(A,R),(R,A),(A,A),(R,R)
    # observed agreement = 3/5 = 0.6
    # human accepts = 3, llm accepts = 3
    # p_e = (3/5*3/5) + (2/5*2/5) = 9/25 + 4/25 = 13/25 = 0.52
    # kappa = (0.6 - 0.52) / (1 - 0.52) = 0.08 / 0.48 = 0.16666... -> 0.167
    pairs = [
        (rv("accept", 3, 3, 3), rv("accept", 3, 3, 3)),
        (rv("accept", 3, 3, 3), rv("reject", 3, 3, 3)),
        (rv("reject", 3, 3, 3), rv("accept", 3, 3, 3)),
        (rv("accept", 3, 3, 3), rv("accept", 3, 3, 3)),
        (rv("reject", 3, 3, 3), rv("reject", 3, 3, 3)),
    ]
    r = agreement(pairs)
    assert r["verdict_agreement"] == 0.6
    assert r["kappa"] == 0.167
    assert r["confusion"] == {
        "accept/accept": 2,
        "accept/reject": 1,
        "reject/accept": 1,
        "reject/reject": 1,
    }


def test_missing_scores():
    human = {"verdict": "accept", "scores": {"correctness": 4}, "failure_mode": "x"}
    llm = {"verdict": "accept", "scores": {"correctness": 3, "maintainability": 2}, "failure_mode": "x"}
    r = agreement([(human, llm)])
    # correctness diff 1, maintainability skipped, test_quality skipped
    assert r["score_mae"]["correctness"] == 1.0
    assert r["score_mae"]["maintainability"] is None
    assert r["score_mae"]["test_quality"] is None
    assert r["score_mae"]["overall"] == 1.0
    assert r["within_one"] == 1.0


def test_n_zero():
    r = agreement([])
    assert r["n"] == 0
    assert r["verdict_agreement"] is None
    assert r["kappa"] is None
    assert r["score_mae"] == {
        "correctness": None,
        "maintainability": None,
        "test_quality": None,
        "overall": None,
    }
    assert r["within_one"] is None
    assert r["failure_mode_agreement"] is None
    assert r["confusion"] == {
        "accept/accept": 0,
        "accept/reject": 0,
        "reject/accept": 0,
        "reject/reject": 0,
    }


def test_pair_up_latest():
    reviews = [
        {"key": "b", "source": "human", "created_at": 1.0, "v": "old"},
        {"key": "b", "source": "human", "created_at": 5.0, "v": "new"},
        {"key": "b", "source": "llm:m1", "created_at": 4.0, "v": "old-llm"},
        {"key": "b", "source": "llm:m1", "created_at": 2.0, "v": "older-llm"},
        {"key": "b", "source": "llm:m2", "created_at": 9.0, "v": "new-llm"},
        {"key": "a", "source": "human", "created_at": 3.0, "v": "a-h"},
        {"key": "a", "source": "llm:m1", "created_at": 3.0, "v": "a-l"},
        {"key": "c", "source": "human", "created_at": 1.0, "v": "no-llm"},
    ]
    pairs = pair_up(reviews)
    assert [h["key"] for h, _ in pairs] == ["a", "b"]
    assert pairs[0][0]["v"] == "a-h"
    assert pairs[0][1]["v"] == "a-l"
    assert pairs[1][0]["v"] == "new"
    # latest llm across models wins
    assert pairs[1][1]["v"] == "new-llm"
