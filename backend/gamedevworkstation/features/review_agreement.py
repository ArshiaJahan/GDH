"""Review Desk: how often an LLM pre-review agrees with the human review of the same trial."""
from __future__ import annotations

from collections import defaultdict

DIMENSIONS = ("correctness", "maintainability", "test_quality")
KEYS = ("accept/accept", "accept/reject", "reject/accept", "reject/reject")


def _round(x):
    if x is None:
        return None
    return round(x, 3)


def agreement(pairs: list[tuple[dict, dict]]) -> dict:
    n = len(pairs)

    if n == 0:
        return {
            "n": 0,
            "verdict_agreement": None,
            "kappa": None,
            "score_mae": {d: None for d in DIMENSIONS} | {"overall": None},
            "within_one": None,
            "failure_mode_agreement": None,
            "confusion": {k: 0 for k in KEYS},
        }

    matches = 0
    fm_matches = 0
    confusion = defaultdict(int)
    abs_diffs = {d: [] for d in DIMENSIONS}

    for human, llm in pairs:
        hv = human.get("verdict")
        lv = llm.get("verdict")
        if hv == lv:
            matches += 1
        confusion[f"{hv}/{lv}"] += 1
        if human.get("failure_mode") == llm.get("failure_mode"):
            fm_matches += 1
        hs = human.get("scores", {})
        ls = llm.get("scores", {})
        for d in DIMENSIONS:
            if d in hs and d in ls:
                abs_diffs[d].append(abs(hs[d] - ls[d]))

    n_accept_h = sum(1 for h, _ in pairs if h.get("verdict") == "accept")
    n_accept_l = sum(1 for _, l in pairs if l.get("verdict") == "accept")
    n_reject_h = n - n_accept_h
    n_reject_l = n - n_accept_l

    p_o = matches / n
    p_e = (n_accept_h * n_accept_l + n_reject_h * n_reject_l) / (n * n)
    if p_e == 1:
        kappa = 1.0 if p_o == 1 else 0.0
    else:
        kappa = (p_o - p_e) / (1 - p_e)

    score_mae = {}
    for d in DIMENSIONS:
        vals = abs_diffs[d]
        score_mae[d] = _round(sum(vals) / len(vals)) if vals else None
    all_vals = [v for d in DIMENSIONS for v in abs_diffs[d]]
    score_mae["overall"] = (
        _round(sum(all_vals) / len(all_vals)) if all_vals else None
    )

    within_one = (
        _round(sum(1 for v in all_vals if v <= 1) / len(all_vals))
        if all_vals
        else None
    )

    return {
        "n": n,
        "verdict_agreement": _round(p_o),
        "kappa": _round(kappa),
        "score_mae": score_mae,
        "within_one": within_one,
        "failure_mode_agreement": _round(fm_matches / n),
        "confusion": {k: confusion.get(k, 0) for k in KEYS},
    }


def pair_up(reviews: list[dict]) -> list[tuple[dict, dict]]:
    humans: dict[str, dict] = {}
    llms: dict[str, dict] = {}
    for r in reviews:
        key = r["key"]
        if r["source"] == "human":
            if key not in humans or r["created_at"] > humans[key]["created_at"]:
                humans[key] = r
        elif r["source"].startswith("llm:"):
            if key not in llms or r["created_at"] > llms[key]["created_at"]:
                llms[key] = r
    return [
        (humans[k], llms[k]) for k in sorted(set(humans) & set(llms))
    ]
