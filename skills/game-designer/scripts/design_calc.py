#!/usr/bin/env python3
"""design_calc.py - dependency-free game design calculator (Python 3.8+).

Subcommands:
  curve  level -> XP table (linear / poly / exp / logistic)
  ev     expected value of a loot table (value:prob pairs)
  odds   P(at least one success in n tries) and tries needed for X% confidence
  pity   expected pulls with a hard pity and optional soft-pity ramp
  prd    Dota-style pseudo-random distribution constant C
  ttk    time-to-kill from HP, damage, fire rate, accuracy, crit, armor

Run `python design_calc.py <subcommand> --help` for examples.
"""
import argparse
import math
import random
import sys


# ---------------------------------------------------------------- curve
def cmd_curve(a):
    rows = []
    cum = 0.0
    for lvl in range(1, a.levels + 1):
        if a.type == "linear":
            xp = a.base + a.step * (lvl - 1)
        elif a.type == "poly":
            xp = a.base * (lvl ** a.exponent)
        elif a.type == "exp":
            xp = a.base * (a.growth ** (lvl - 1))
        else:  # logistic: per-level cost follows an S-curve from ~0 to cap
            mid = a.mid if a.mid is not None else a.levels / 2.0
            xp = a.cap / (1.0 + math.exp(-a.k * (lvl - mid)))
        xp = max(0.0, xp)
        rows.append((lvl, xp, cum))
        cum += xp
    print("Curve: %s   (XP column = cost to go from level L to L+1)" % a.type)
    print("%6s %14s %16s %9s" % ("Level", "XP to next", "Cumulative XP", "Ratio"))
    prev = None
    for lvl, xp, c in rows:
        ratio = "%.3f" % (xp / prev) if prev else "-"
        print("%6d %14s %16s %9s" % (lvl, "{:,.0f}".format(round(xp)), "{:,.0f}".format(round(c)), ratio))
        prev = xp if xp > 0 else None
    total = sum(r[1] for r in rows[:-1])
    print("Total XP to reach level %d: %s" % (a.levels, "{:,.0f}".format(round(total))))
    if a.xp_per_hour:
        print("At %s XP/hour: %.1f hours to level %d" % (a.xp_per_hour, total / a.xp_per_hour, a.levels))


# ------------------------------------------------------------------- ev
def cmd_ev(a):
    pairs = []
    for item in a.items:
        try:
            v, p = item.split(":")
            pairs.append((float(v), float(p)))
        except ValueError:
            sys.exit("Bad item '%s'; use value:prob, e.g. 100:0.05" % item)
    total_p = sum(p for _, p in pairs)
    if a.percent:
        pairs = [(v, p / 100.0) for v, p in pairs]
        total_p /= 100.0
    if total_p > 1.0 + 1e-9:
        print("Warning: probabilities sum to %.4f (>1); normalising." % total_p)
        pairs = [(v, p / total_p) for v, p in pairs]
    elif total_p < 1.0 - 1e-9:
        print("Note: probabilities sum to %.4f; remaining %.4f treated as value %s (--rest)."
              % (total_p, 1 - total_p, a.rest))
        pairs.append((a.rest, 1.0 - total_p))
    mean = sum(v * p for v, p in pairs)
    var = sum(p * (v - mean) ** 2 for v, p in pairs)
    print("Expected value per roll : %.4f" % mean)
    print("Variance / std dev      : %.4f / %.4f" % (var, math.sqrt(var)))
    if a.cost:
        print("Cost per roll           : %.4f  -> net EV %.4f, return %.1f%%"
              % (a.cost, mean - a.cost, 100.0 * mean / a.cost))
    if a.rolls and a.rolls > 1:
        print("Over %d rolls           : mean %.2f, std dev %.2f (independent rolls)"
              % (a.rolls, mean * a.rolls, math.sqrt(var * a.rolls)))


# ----------------------------------------------------------------- odds
def cmd_odds(a):
    p = a.p / 100.0 if a.percent else a.p
    if not 0 < p < 1:
        sys.exit("p must be between 0 and 1 (exclusive)")
    if a.n is not None:
        pr = 1 - (1 - p) ** a.n
        exp_k = a.n * p
        print("P(at least 1 success in %d tries at p=%.5g) = %.4f%%" % (a.n, p, 100 * pr))
        print("P(zero successes)                          = %.4f%%" % (100 * (1 - p) ** a.n))
        print("Expected successes                         = %.3f" % exp_k)
        if a.k and a.k > 1:
            # P(X >= k) binomial
            cdf = sum(math.comb(a.n, i) * p ** i * (1 - p) ** (a.n - i) for i in range(a.k))
            print("P(at least %d successes)                    = %.4f%%" % (a.k, 100 * (1 - cdf)))
    print("Mean tries to first success (1/p)          = %.2f" % (1 / p))
    print("Tries needed for confidence (at least 1 success):")
    for c in a.confidence:
        cc = c / 100.0
        n = math.ceil(math.log(1 - cc) / math.log(1 - p))
        print("  %5.1f%% -> %d tries" % (c, n))


# ----------------------------------------------------------------- pity
def pity_probs(a):
    """Per-pull success probability by pull index since last success (1-based)."""
    probs = []
    for n in range(1, a.hard + 1):
        if n >= a.hard:
            pn = 1.0
        elif a.soft_start and n >= a.soft_start:
            pn = min(1.0, a.p + (n - a.soft_start + 1) * a.soft_inc)
        else:
            pn = a.p
        probs.append(pn)
    return probs


def cmd_pity(a):
    if a.percent:
        a.p /= 100.0
        a.soft_inc /= 100.0
    probs = pity_probs(a)
    surv = 1.0
    expected = 0.0
    cdf = []
    cum = 0.0
    for n, pn in enumerate(probs, 1):
        pmf = surv * pn
        expected += n * pmf
        cum += pmf
        cdf.append(cum)
        surv *= (1 - pn)
    print("Base p=%.4f  hard pity=%d  soft start=%s  soft step=%.4f"
          % (a.p, a.hard, a.soft_start or "none", a.soft_inc))
    print("Expected pulls per success      : %.2f  (no pity: %.2f)" % (expected, 1 / a.p))
    print("Effective rate (1/expected)     : %.4f%%" % (100 / expected))
    for q in (0.5, 0.9, 0.99):
        n = next(i for i, c in enumerate(cdf, 1) if c >= q)
        print("Pulls for %2d%% confidence        : %d" % (q * 100, n))
    if a.cost:
        print("Expected cost per success       : %.2f (cost/pull %.2f)" % (expected * a.cost, a.cost))
    if a.sim:
        rng = random.Random(a.seed)
        tot = 0
        worst = 0
        for _ in range(a.sim):
            for i, pn in enumerate(probs, 1):
                if rng.random() < pn:
                    break
            tot += i
            worst = max(worst, i)
        print("Monte Carlo (%d runs)        : mean %.2f pulls, max seen %d" % (a.sim, tot / a.sim, worst))


# ------------------------------------------------------------------ prd
def prd_expected_p(c):
    """Overall success probability for PRD constant c: 1 / E[tries]."""
    surv = 1.0
    e = 0.0
    n = 1
    while True:
        pn = min(1.0, c * n)
        e += surv  # E[N] = sum_{k>=0} P(N>k)
        surv *= (1 - pn)
        if pn >= 1.0 or surv < 1e-15:
            break
        n += 1
    return 1.0 / e


def prd_constant(p):
    lo, hi = 0.0, 1.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if prd_expected_p(mid) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def cmd_prd(a):
    for nominal in a.p:
        p = nominal / 100.0 if a.percent else nominal
        if not 0 < p < 1:
            sys.exit("p must be between 0 and 1 (exclusive)")
        c = prd_constant(p)
        n_max = math.ceil(1 / c)
        print("Nominal p = %.4f -> C = %.6f   (P on attempt N = C*N; guaranteed by attempt %d)"
              % (p, c, n_max))
        if a.table:
            surv = 1.0
            for n in range(1, n_max + 1):
                pn = min(1.0, c * n)
                print("   attempt %2d: P=%6.2f%%   P(first success here)=%6.2f%%   cumulative=%6.2f%%"
                      % (n, 100 * pn, 100 * surv * pn, 100 * (1 - surv * (1 - pn))))
                surv *= (1 - pn)
        if a.sim:
            rng = random.Random(a.seed)
            hits = 0
            streak = 0
            longest = 0
            cur = 0
            fails = 0
            for _ in range(a.sim):
                fails += 1
                if rng.random() < min(1.0, c * fails):
                    hits += 1
                    fails = 0
                    cur = 0
                else:
                    cur += 1
                    longest = max(longest, cur)
            print("   simulated %d trials: observed rate %.4f, longest failure streak %d"
                  % (a.sim, hits / a.sim, longest))
            # compare with pure random
            streak_pure = 0
            cur = 0
            for _ in range(a.sim):
                if rng.random() < p:
                    cur = 0
                else:
                    cur += 1
                    streak_pure = max(streak_pure, cur)
            print("   pure random streak for comparison: longest failure streak %d" % streak_pure)


# ------------------------------------------------------------------ ttk
def cmd_ttk(a):
    dmg = a.damage
    if a.armor_mode == "flat":
        dmg_a = max(a.min_damage, dmg - a.armor)
    else:  # ratio: reduction = armor / (armor + k)
        dmg_a = dmg * (1 - a.armor / (a.armor + a.armor_k)) if a.armor >= 0 else dmg
    hit_avg = dmg_a * (1 + a.crit * (a.crit_mult - 1))
    exp_per_shot = a.accuracy * hit_avg
    if exp_per_shot <= 0:
        sys.exit("Expected damage per shot is zero.")
    shots_exp = a.hp / exp_per_shot
    best_shots = math.ceil(a.hp / (dmg_a * a.crit_mult)) if a.crit > 0 else math.ceil(a.hp / dmg_a)
    plain_shots = math.ceil(a.hp / dmg_a)
    rate = a.fire_rate
    ttk = lambda shots: max(0.0, shots - 1) / rate if rate > 0 else float("inf")
    dps_theory = dmg_a * rate
    dps_eff = exp_per_shot * rate
    print("Damage per hit after armor     : %.2f  (raw %.2f, mode %s)" % (dmg_a, dmg, a.armor_mode))
    print("Average damage per hit (crits) : %.2f" % hit_avg)
    print("Theoretical DPS (all hit)      : %.2f" % dps_theory)
    print("Effective DPS (acc+crit)       : %.2f" % dps_eff)
    print("Shots to kill, best case       : %d  (all hits are crits)" % best_shots)
    print("Shots to kill, no crits        : %d  (all hit)" % plain_shots)
    print("Shots to kill, expected        : %.2f (incl. misses)" % shots_exp)
    print("TTK best / no-crit / expected  : %.3fs / %.3fs / %.3fs  (first shot at t=0)"
          % (ttk(best_shots), ttk(plain_shots), ttk(math.ceil(shots_exp))))
    if a.reaction:
        print("TTK incl. %.2fs reaction/aim   : %.3fs expected" % (a.reaction, a.reaction + ttk(math.ceil(shots_exp))))
    if a.sim:
        rng = random.Random(a.seed)
        res = []
        for _ in range(a.sim):
            hp = a.hp
            shots = 0
            while hp > 0 and shots < 10000:
                shots += 1
                if rng.random() < a.accuracy:
                    d = dmg_a * (a.crit_mult if rng.random() < a.crit else 1.0)
                    hp -= d
            res.append(ttk(shots))
        res.sort()
        print("Monte Carlo (%d runs) TTK       : mean %.3fs, p50 %.3fs, p90 %.3fs, p99 %.3fs"
              % (a.sim, sum(res) / len(res), res[len(res) // 2],
                 res[int(len(res) * 0.9)], res[min(len(res) - 1, int(len(res) * 0.99))]))


# ----------------------------------------------------------------- main
EPILOG = """examples:
  design_calc.py curve --type exp --levels 20 --base 100 --growth 1.15
  design_calc.py ev 100:0.01 10:0.2 1:0.5 --cost 5
  design_calc.py odds --p 0.02 --n 50 --confidence 50 90 99
  design_calc.py pity --p 0.006 --hard 90 --soft-start 74 --soft-inc 0.06
  design_calc.py prd --p 0.25 --table
  design_calc.py ttk --hp 100 --damage 24 --fire-rate 8 --accuracy 0.7 --crit 0.1 --crit-mult 2 --armor 30
"""


def build():
    ap = argparse.ArgumentParser(prog="design_calc.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=EPILOG)
    sp = ap.add_subparsers(dest="cmd", required=True)
    F = argparse.RawDescriptionHelpFormatter

    c = sp.add_parser("curve", formatter_class=F, help="level -> XP table",
                      description="Print a level->XP table.\n"
                                  "  linear  : xp = base + step*(L-1)\n"
                                  "  poly    : xp = base * L^exponent\n"
                                  "  exp     : xp = base * growth^(L-1)\n"
                                  "  logistic: xp = cap / (1 + e^(-k*(L-mid)))  (S-curve, plateaus at cap)\n\n"
                                  "examples:\n  design_calc.py curve --type poly --base 50 --exponent 2 --levels 30\n"
                                  "  design_calc.py curve --type logistic --cap 5000 --k 0.3 --mid 15 --levels 30")
    c.add_argument("--type", choices=["linear", "poly", "exp", "logistic"], default="poly")
    c.add_argument("--levels", type=int, default=20)
    c.add_argument("--base", type=float, default=100.0)
    c.add_argument("--step", type=float, default=100.0, help="linear: added per level")
    c.add_argument("--exponent", type=float, default=2.0, help="poly exponent (2-3 typical)")
    c.add_argument("--growth", type=float, default=1.15, help="exp growth per level (1.05-1.3 typical)")
    c.add_argument("--cap", type=float, default=10000.0, help="logistic max XP per level")
    c.add_argument("--k", type=float, default=0.3, help="logistic steepness")
    c.add_argument("--mid", type=float, default=None, help="logistic midpoint level (default levels/2)")
    c.add_argument("--xp-per-hour", type=float, default=0, help="optional: convert total XP to hours")
    c.set_defaults(fn=cmd_curve)

    e = sp.add_parser("ev", formatter_class=F, help="expected value of a loot table",
                      description="Expected value of a loot table given value:prob pairs.\n\n"
                                  "examples:\n  design_calc.py ev 1000:0.001 50:0.05 5:0.4 --cost 3\n"
                                  "  design_calc.py ev 100:1 10:20 1:79 --percent")
    e.add_argument("items", nargs="+", help="value:prob pairs, e.g. 100:0.05")
    e.add_argument("--percent", action="store_true", help="probabilities are given in percent")
    e.add_argument("--rest", type=float, default=0.0, help="value of the unlisted remainder (default 0)")
    e.add_argument("--cost", type=float, default=0.0, help="price per roll, to get net EV and return")
    e.add_argument("--rolls", type=int, default=0, help="also show mean/std over N rolls")
    e.set_defaults(fn=cmd_ev)

    o = sp.add_parser("odds", formatter_class=F, help="at-least-one probability and tries for confidence",
                      description="P(at least one success) = 1-(1-p)^n ; n for confidence c = ln(1-c)/ln(1-p).\n\n"
                                  "examples:\n  design_calc.py odds --p 0.02 --n 50\n"
                                  "  design_calc.py odds --p 1 --percent --confidence 50 90 99\n"
                                  "  design_calc.py odds --p 0.1 --n 30 --k 5")
    o.add_argument("--p", type=float, required=True, help="per-try success probability (0-1, or percent with --percent)")
    o.add_argument("--percent", action="store_true")
    o.add_argument("--n", type=int, help="number of tries")
    o.add_argument("--k", type=int, help="also show P(at least k successes in n) (binomial)")
    o.add_argument("--confidence", type=float, nargs="+", default=[50, 90, 95, 99], help="percent levels")
    o.set_defaults(fn=cmd_odds)

    pi = sp.add_parser("pity", formatter_class=F, help="expected pulls with hard/soft pity",
                       description="Per-pull chance is p until --soft-start, then rises by --soft-inc per pull,\n"
                                   "and is 100%% at --hard. Exact expectation by dynamic programming.\n\n"
                                   "examples:\n  design_calc.py pity --p 0.006 --hard 90 --soft-start 74 --soft-inc 0.06 --sim 100000\n"
                                   "  design_calc.py pity --p 0.02 --hard 50")
    pi.add_argument("--p", type=float, required=True, help="base chance per pull")
    pi.add_argument("--hard", type=int, required=True, help="pull number with guaranteed success")
    pi.add_argument("--soft-start", type=int, default=0, help="first pull of the ramp (0 = no soft pity)")
    pi.add_argument("--soft-inc", type=float, default=0.0, help="added chance per pull from soft start")
    pi.add_argument("--percent", action="store_true", help="--p and --soft-inc are percents")
    pi.add_argument("--cost", type=float, default=0.0, help="cost per pull")
    pi.add_argument("--sim", type=int, default=0, help="Monte Carlo runs for cross-check")
    pi.add_argument("--seed", type=int, default=1)
    pi.set_defaults(fn=cmd_pity)

    pr = sp.add_parser("prd", formatter_class=F, help="Dota-style pseudo-random distribution constant",
                       description="P(attempt N since last success) = C*N. Finds C so the long-run rate equals\n"
                                   "the nominal probability.\n\n"
                                   "examples:\n  design_calc.py prd --p 0.25 --table\n"
                                   "  design_calc.py prd --p 5 10 20 30 --percent\n"
                                   "  design_calc.py prd --p 0.25 --sim 200000")
    pr.add_argument("--p", type=float, nargs="+", required=True, help="nominal probability(ies)")
    pr.add_argument("--percent", action="store_true")
    pr.add_argument("--table", action="store_true", help="print per-attempt probabilities")
    pr.add_argument("--sim", type=int, default=0, help="simulate to verify and compare streaks")
    pr.add_argument("--seed", type=int, default=1)
    pr.set_defaults(fn=cmd_prd)

    t = sp.add_parser("ttk", formatter_class=F, help="time to kill",
                      description="Time-to-kill from HP, damage, fire rate, accuracy, crit and armor.\n"
                                  "TTK counts (shots-1)/fire_rate: the first shot lands at t=0.\n"
                                  "Armor modes: flat (dmg-armor, min --min-damage) or ratio\n"
                                  "(dmg * (1 - armor/(armor+K)), K default 100; a common MOBA/RPG heuristic).\n\n"
                                  "examples:\n  design_calc.py ttk --hp 100 --damage 24 --fire-rate 8 --accuracy 0.7 --crit 0.1 --crit-mult 2 --armor 30\n"
                                  "  design_calc.py ttk --hp 250 --damage 60 --fire-rate 1.5 --armor 20 --armor-mode flat --sim 20000")
    t.add_argument("--hp", type=float, required=True, help="target hit points (incl. shield)")
    t.add_argument("--damage", type=float, required=True, help="damage per hit")
    t.add_argument("--fire-rate", type=float, required=True, help="shots per second")
    t.add_argument("--accuracy", type=float, default=1.0, help="hit chance 0-1")
    t.add_argument("--crit", type=float, default=0.0, help="crit chance 0-1")
    t.add_argument("--crit-mult", type=float, default=2.0)
    t.add_argument("--armor", type=float, default=0.0)
    t.add_argument("--armor-mode", choices=["flat", "ratio"], default="ratio")
    t.add_argument("--armor-k", type=float, default=100.0, help="ratio mode constant")
    t.add_argument("--min-damage", type=float, default=1.0, help="flat mode damage floor")
    t.add_argument("--reaction", type=float, default=0.0, help="add reaction/aim time in seconds")
    t.add_argument("--sim", type=int, default=0, help="Monte Carlo runs for TTK distribution")
    t.add_argument("--seed", type=int, default=1)
    t.set_defaults(fn=cmd_ttk)
    return ap


def validate(ap, a):
    """Reject bad inputs with a clear argparse error instead of crashing."""
    if a.cmd in ("odds", "pity", "prd"):
        plist = a.p if a.cmd == "prd" else [a.p]
        for raw in plist:
            p = raw / 100.0 if a.percent else raw
            if not 0 < p <= 1:
                ap.error("--p must satisfy 0 < p <= 1 (got %g%s)" % (raw, " percent" if a.percent else ""))
            if a.cmd == "odds" and p >= 1:
                ap.error("odds needs p < 1 (at p = 1 every try succeeds)")
            if a.cmd == "prd" and p >= 1:
                ap.error("prd needs p < 1 (at p = 1 every attempt succeeds)")
    if a.cmd == "odds":
        for c in a.confidence:
            if not 0 < c < 100:
                ap.error("--confidence values must satisfy 0 < c < 100 (got %g)" % c)
    if a.cmd == "pity" and a.hard < 1:
        ap.error("--hard must be >= 1 (got %d)" % a.hard)
    if a.cmd == "ttk":
        if a.fire_rate <= 0:
            ap.error("--fire-rate must be > 0 (got %g)" % a.fire_rate)
        if a.hp <= 0:
            ap.error("--hp must be > 0 (got %g)" % a.hp)


def main(argv=None):
    ap = build()
    a = ap.parse_args(argv)
    validate(ap, a)
    a.fn(a)


if __name__ == "__main__":
    main()
