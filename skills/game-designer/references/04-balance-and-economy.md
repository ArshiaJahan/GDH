# Balance and Economy

Numbers, cost curves, probability, progression math, simulation, metagame tuning and virtual economies. Load this when the task is "make these numbers work".

## Table of Contents

1. [Mindset: What Balance Is For](#1-mindset-what-balance-is-for)
2. [Balance Types](#2-balance-types)
   - [2.1 Transitive](#21-transitive-balance)
   - [2.2 Intransitive](#22-intransitive-balance)
   - [2.3 Fairness and symmetry](#23-fairness-and-symmetry)
   - [2.4 PvE vs PvP](#24-pve-vs-pvp-balance)
3. [Cost Curves and Power Budgets](#3-cost-curves-and-power-budgets)
   - [3.1 Method](#31-method)
   - [3.2 Worked example: card game](#32-worked-example-card-game)
   - [3.3 Worked example: RPG gear](#33-worked-example-rpg-gear)
4. [Combat Math: DPS, TTK, EHP](#4-combat-math-dps-ttk-ehp)
5. [Probability for Designers](#5-probability-for-designers)
6. [Managing Randomness: PRD, Pity, Shuffle Bags](#6-managing-randomness-prd-pity-shuffle-bags)
7. [Progression Curves](#7-progression-curves)
8. [Spreadsheet-Driven Balancing](#8-spreadsheet-driven-balancing)
9. [Simulation and Monte Carlo](#9-simulation-and-monte-carlo)
10. [Metagame Balancing with Pick and Win Rates](#10-metagame-balancing-with-pick-and-win-rates)
11. [Nerf and Buff Philosophy](#11-nerf-and-buff-philosophy)
12. [Virtual Economies](#12-virtual-economies)
    - [12.1 Faucets, sinks, inflation](#121-faucets-sinks-inflation)
    - [12.2 Currencies](#122-currencies-hard-soft-and-more)
    - [12.3 Trading and auction houses](#123-trading-and-auction-houses)
    - [12.4 Lessons from EVE, Ultima Online and Castronova](#124-lessons-from-eve-ultima-online-and-castronova)
13. [Crafting Economies](#13-crafting-economies)
14. [Idle and Incremental Math](#14-idle-and-incremental-math)
15. [Calculator](#15-calculator)
16. [Checklists and Pitfalls](#16-checklists-and-pitfalls)
17. [References](#17-references)

---

## 1. Mindset: What Balance Is For

Balance is not "equal numbers". Balance is the property that **the choices you offer are all worth considering, and the outcomes feel fair for the audience you target**. Pick the goal first:

| Goal | What "balanced" means | Typical tools |
|---|---|---|
| Competitive fairness (PvP) | No dominant strategy, skill decides outcomes, comebacks possible | Win-rate bands, counters, matchmaking |
| Challenge calibration (PvE) | Target fail/clear rates per encounter | Telemetry, TTK/EHP targets, tuning knobs |
| Economic health | Stable prices, no runaway inflation, meaningful scarcity | Faucet/sink accounting, price indices |
| Progression pacing | Time-to-milestone matches intended hours | XP curves, drop-rate math |
| Perceived fairness | Players do not feel cheated by RNG or monetization | Pity, bad-luck protection, transparency |

Process loop (use every time): **define target -> model on paper -> spreadsheet -> simulate -> playtest -> read telemetry -> adjust one variable -> repeat.** Theory gets you within ~30 percent (heuristic); playtests close the gap.

Rules of thumb:
- Make every number a **named parameter** in one place (a data table), never a magic constant in code.
- Design for the **ratio** between numbers, not the absolute values. Absolute values can be rescaled later; broken ratios cannot.
- Balance **for the best players on the extreme, and for the median player on the average**. A tool that is unfair only in expert hands is a different problem from one that is unfair to everyone.
- Keep early-game numbers small and human-readable (damage 5 vs 7, not 5.38 vs 7.12). Large numbers are fine for late-game feel, but only if scaling is consistent (see section 7).

## 2. Balance Types

### 2.1 Transitive balance

"Higher cost means more power." Items, units, cards or levels are ordered on one axis of strength; price must keep pace. Examples: a 5-mana minion beats a 3-mana minion; a +10 sword beats a +5 sword.

- Tool: the **cost curve** (section 3). Everything is converted to a shared currency (mana, gold, "power points").
- Failure modes: a cheap item above the curve (always-pick), an expensive item below it (never-pick, a "trap option"), or a curve that is linear in cost while real value is non-linear (e.g. 2x stats at 2x cost, but 2x stats is worth 3x in combat because of focus-fire or one-shot thresholds).
- Always check **efficiency per slot** if slots are limited (hand size, inventory, party size, deck size). Limited slots make high-end items more valuable than their raw stats suggest.

### 2.2 Intransitive balance

Rock-paper-scissors: A beats B beats C beats A. No option is "better", only better against something. Examples: Starcraft race matchups and unit counters, fighting game archetypes (zoner > grappler > rushdown > zoner is a common heuristic), Pokemon types, Magic archetypes (one common heuristic: aggro beats control, control beats combo, combo beats aggro; orderings vary by format and are debated).

Design rules:
1. Draw the **payoff matrix** (rows = your choice, columns = opponent choice, cells = expected win chance or value). A mixed-strategy equilibrium exists if no row dominates another.
2. Make counters **soft**, not hard (60/40, not 100/0). A hard counter turns the game into a guess; a soft counter rewards skill and prediction.
3. Counters should require **information or commitment**. If the counter-picker always sees your pick first (late pick, scouting), RPS collapses into a pure information game.
4. Beware **cycles longer than 3** with unequal edges; they hide dominant options. Compute the matrix's equilibrium frequencies (a short LP or iterative best-response in a script is enough).
5. Use **Rock-Paper-Scissors with a twist**: each option has a hidden, learnable tell, so skill beats pure luck.

For the underlying game theory (Nash equilibrium, mixed strategies, yomi and prediction layers) see `14-ai-procedural-and-audio-design.md`; this file only uses the payoff matrix as a balance check.

Example 3x3 payoff matrix (win chance for the row player), a healthy soft-counter design:

| Row \ Col | Rush | Economy | Defense |
|---|---|---|---|
| Rush | 50% | 65% | 40% |
| Economy | 35% | 50% | 62% |
| Defense | 60% | 38% | 50% |

Check: each row has one good, one neutral, one bad matchup; no row's average exceeds 50% by much (Rush 51.7, Economy 49, Defense 49.3: acceptable).

### 2.3 Fairness and symmetry

| Approach | Description | Pros | Cons |
|---|---|---|---|
| Perfect symmetry | Same start, same options (Chess apart from first move, most RTS mirror modes) | Trivially fair, easy to read | Less variety, less identity |
| Mirrored asymmetry | Different pieces, same budget (fighting game rosters, MOBA heroes) | Variety, identity | Needs constant tuning |
| Asymmetric roles | Different goals (Dead by Daylight, Root, Evolve) | Unique fantasy | Hardest to balance; needs separate win-rate targets |
| Handicap / catch-up | Weaker players get a boost | Mixed-skill groups | Feels patronizing if visible |

Heuristic: asymmetric games should target **50% win rate per side at the intended skill level**, but allow side-specific deviations (45-55%) if the weaker side is more fun to play (heuristic).

Fairness tools: simultaneous turns, alternating first move with compensation (pie rule: one player splits, the other chooses), draft/pick-ban, symmetric map pairs, randomized-but-mirrored resources.

### 2.4 PvE vs PvP balance

| Axis | PvE | PvP |
|---|---|---|
| Goal | Challenge, power fantasy, pacing | Fair competition, skill expression |
| "Overpowered" | Often acceptable (fun) if it does not trivialize | Not acceptable if it is dominant |
| Data | Clear/fail rates, deaths per encounter, session time | Pick rate, win rate, ban rate, skill-bracket splits |
| Fix style | Tune encounters and drops; buff weak options freely | Prefer small, communicated changes; re-test counters |
| Dangers | Optimal build trivializes content; players feel forced into one build | Frustration with unavoidable losses, snowballing, meta stagnation |

For games with both (MMOs, Destiny, Diablo-likes), keep **separate tuning layers** (e.g. a PvP-only damage coefficient). One set of numbers for both modes is the classic source of "nerfed in PvP, ruined PvE" complaints.

## 3. Cost Curves and Power Budgets

### 3.1 Method

A **cost curve** (Schreiber 2010, Schreiber and Romero 2021) maps price to total benefit, using a common unit.

1. **Pick the unit.** Usually the resource players pay (mana, gold, action points, deck slots). If several resources exist, convert them using their relative scarcity.
2. **Baseline.** Define one "vanilla" item (no special effects) at each cost: its raw stats define the curve. Pick a simple function, e.g. `stats(cost) = a*cost + b`.
3. **Price effects.** Give each ability or modifier a value in the same unit. Estimate by playtests or by the "is this equal to X extra points?" test; refine with win-rate data.
4. **Account for tempo and scarcity.** Cheap items get a discount per unit of power because they are easier to deploy (tempo); hard-to-obtain items (rare resource, long cooldown) deserve a premium.
5. **Add negative costs.** Drawbacks (self-damage, delay, restriction) are negative values that fund extra power.
6. **Spot the outliers.** Plot every item as (cost, power). Anything notably above the line is overpowered; below, underpowered or a design-space opportunity (a "swingy" or niche role is fine if it is intentional).
7. **Iterate with data**: items with win-rate-when-included or pick rate far from the average are the first to re-cost.

Rule: **the curve does not have to be linear.** Many card games use a slightly super-linear curve (a 2x cost item is worth a bit more than 2x power) to compensate for tempo loss and for slot efficiency; this is a heuristic and a design choice, not a law.

### 3.2 Worked example: card game

Goal: 10-card sample of creatures with cost 1-7, using the common "vanilla test" heuristic (a vanilla creature of cost N has about `2N + 1` total stats, split attack/health). This pattern is widely cited in digital card game design (heuristic, tune with data).

Unit: 1 stat point (attack or health).

```
vanilla(N) = 2N + 1                       # total stats
Ability price list (stat points):
  Taunt / guard ............... 1.0
  Charge / haste .............. 1.5
  Draw a card ................. 2.0
  Deal 2 damage (battlecry) ... 2.0
  Deathrattle: 1/1 token ...... 1.5
  Drawback: cannot attack ..... -2.5
  Drawback: lose 2 HP on play . -1.0
```

Design three cards:

| Card | Cost | Budget (2N+1) | Text | Stats used | Check |
|---|---|---|---|---|---|
| Wall Guard | 3 | 7 | Taunt | 7 - 1.0 = 6 -> 2/4 | OK |
| Scout | 2 | 5 | Draw a card | 5 - 2.0 = 3 -> 2/1 | OK |
| Raider | 4 | 9 | Charge | 9 - 1.5 = 7.5 -> 4/3 (rounded down 7) | OK |
| Frail Artillery | 5 | 11 | Deal 2 damage, cannot attack | 11 - 2.0 + 2.5 = 11.5 -> 6/5 | Check: a 6/5 that cannot attack acts as a wall plus ping; confirm in tests |

Sanity checks to run on any card set:
- **Efficiency on curve**: compute `power / budget` for every card; flag values outside 0.9-1.1 (heuristic band).
- **Combo risk**: the budget assumes cards in isolation. Any pair whose combined power exceeds the sum of its parts (synergy) needs explicit review (e.g. "gain Taunt" + "Taunt creatures get +2 attack").
- **Variance**: random effects get a discount equal to the **risk premium** (a 50% chance of 4 damage is worth about 2 damage plus some variance bonus for swingy outcomes; usually value it at EV minus a small amount if the effect is bad when it fails).

### 3.3 Worked example: RPG gear

Goal: weapon stat budgets for a game where the player gets a new weapon tier every 5 levels.

```
power_budget(ilvl) = base * growth^(ilvl/5)           # e.g. base=20, growth=1.35
primary stat       = budget * 0.60
secondary stats    = budget * 0.40  split among 1-3 affixes
Affix weight (cost per budget point):
  Attack power ............. 1.00
  Crit chance (per 1%) ..... 0.40 budget pts (crit adds EV = crit% * (mult-1); at mult 2, 1% crit = +1% DPS)
  Attack speed (per 1%) .... 0.40 (1% attack speed = +1% DPS)
  Life steal (per 1%) ...... 3.00 (not derived here; price from the healing it is worth in your game)
Rarity multiplier (budget x): common 1.0, uncommon 1.15, rare 1.35, epic 1.6 (heuristic)
```

Worked numbers: ilvl 15, so `budget = 20 * 1.35^3 = 49.2`. Rare multiplier 1.35, so budget 66.4. Primary 60 percent = 39.8 attack power. Secondary 26.6 points.

Deriving the prices: one attack-power point adds `1/39.8 = 2.51%` DPS on the 39.8 base. One percent crit chance at crit_mult 2.0 adds `0.01*(2-1) = 1%` DPS, which equals `1% / 2.51% = 0.40` attack-power points. One percent attack speed also adds 1% DPS, so it is also 0.40. That is the equal-marginal-value price (each budget point buys the same DPS at the baseline).

Spending: 10 points on crit = 10/0.40 = 25% crit chance; 16.6 points on attack speed = 16.6/0.40 = 41.5%. DPS multiplier = `(1 + 0.25*(2-1)) * (1 + 0.415) = 1.25 * 1.415 = 1.769` -> +76.9%. Compare to putting all 26.6 points in attack power: `1 + 26.6/39.8 = 1.668` -> +66.8%. The split beats pure attack power by about 10 points of DPS even though prices are equal at the margin, because crit and attack speed multiply each other (the multiplicative stacking pitfall below). Fix it by lowering the prices as the player stacks (diminishing returns), capping crit chance, or pricing the second affix at its marginal value given the first. The lesson: derive affix prices from DPS equivalence (do the arithmetic, not intuition), then re-check the full stack.

Verification: compute `DPS_equivalent` for every affix (EV impact per budget point) and make them equal at the baseline; this is the **equal-marginal-value** rule. Then compute the combined build, since the marginal values drift once affixes multiply.

Pitfalls:
- **Multiplicative stacking** (crit chance x crit multiplier x attack speed x +% damage) grows super-linearly; the budget must be defined in log-space or you get power creep per slot. Prefer additive pools with diminishing returns, or cap multipliers.
- **Breakpoints** (cooldown reduction floors, hit-cap) make some points worth zero, others worth a lot; show the player where the breakpoint is, or smooth the function.
- **Legendary/unique** items can exceed the budget by design, but then they must be rare **and** conditional (build-defining, not strictly better).

## 4. Combat Math: DPS, TTK, EHP

Core definitions:

```
DPS_theoretical = damage_per_hit * hits_per_second
DPS_effective   = DPS_theoretical * accuracy * (1 + crit_chance * (crit_mult - 1)) * uptime
TTK             = (shots_to_kill - 1) / fire_rate        # first shot at t=0; add reaction/aim time separately
shots_to_kill   = ceil(HP / damage_after_mitigation)
EHP             = HP / (1 - damage_reduction)            # effective health
```

Mitigation models:

| Model | Formula | Property |
|---|---|---|
| Flat | `dmg' = max(min_dmg, dmg - armor)` | Armor is strong vs many small hits, useless vs big hits; risks immunity (use a floor) |
| Ratio / hyperbolic | `reduction = armor / (armor + K)`; EHP = HP * (1 + armor/K) | Diminishing returns, never reaches 100%; each armor point adds the same EHP percent (K=100 is the League of Legends-style form) |
| Percent capped | `reduction = min(cap, armor * x)` | Simple, but wasted stats past the cap |
| Layered | Shield then HP then armor... | Order of layers changes effective cost; define clearly |

Worked example (ratio model, K = 100), same step (+50 armor) on two units. Unit A: HP 100, armor 50: `reduction = 50/150 = 33.3%`, `EHP = 100 * (1 + 0.5) = 150`. After +50 armor (100): `reduction 50%`, `EHP = 100 * 2 = 200`, a gain of 50 EHP. Unit B: HP 300, armor 50: `EHP = 300 * 1.5 = 450`; after +50 armor, `EHP = 300 * 2 = 600`, a gain of 150 EHP. The same armor step is worth three times as much on the 300-HP unit (armor is worth more on high-HP characters; HP is worth more on high-armor characters; the product HP * (1+armor/K) is what you balance).

Time-to-kill (TTK) design:
- TTK is among the most important numbers in a shooter (practitioner consensus; see also the Halo 3 sniper talk, Griesemer 2010, on how one timing parameter redefines a weapon's role). Short TTK rewards first shot and positioning; long TTK rewards tracking, ability use, and retreat-and-heal.
- Heuristic bands: tactical shooters ~0.2-0.5 s from full health; arena/hero shooters ~0.5-1.5 s; tank/tanky RPG fights 10-60 s. These are rough conventions, not rules; measure what your reaction window demands.
- **Reaction-time floor**: if TTK is below human reaction time plus network latency (~250 ms average visual reaction plus lag, heuristic), the defender can never respond; the game becomes a first-strike lottery.
- **Variance in TTK** matters as much as its mean. Crit, spread and damage falloff create a distribution; players read the *worst realistic* outcome. Prefer low-variance TTK in PvP (deterministic bullet counts) and high variance only if it creates drama in PvE.
- For MOBA and RPG: balance **burst vs sustained** separately. Burst = damage in the first 2 seconds; sustained = average over 10+ seconds. Cooldown-based abilities distort DPS comparisons, so compute both.
- Pair TTK with **time-to-be-killed**: the attacker's TTK is the defender's reaction window. Always evaluate the matchup in both directions.

Use the calculator (`ttk`) to compare weapons; see section 15.

Healing and sustain: `net_damage_rate = enemy_DPS - heal_per_second`; if healing >= incoming DPS, the fight stalls (stalemate threshold). Always ask "what is the break-even DPS that can kill a healer?" and ensure it exists (burst, anti-heal, focus-fire).

## 5. Probability for Designers

The minimum toolbox. Every formula is in code form so it can be pasted into a sheet or script.

```
Expected value (EV) of one roll:        EV = sum(value_i * p_i)
Variance:                               Var = sum(p_i * (value_i - EV)^2)     std dev = sqrt(Var)
n independent rolls:                    EV_n = n*EV     Var_n = n*Var
P(at least one success in n tries):     P = 1 - (1 - p)^n
Tries needed for confidence c:          n = ceil( ln(1 - c) / ln(1 - p) )
Expected tries to first success:        1 / p
Binomial P(exactly k in n):             C(n,k) * p^k * (1-p)^(n-k)
P(A and B) independent:                 p_A * p_B
P(A or B) independent:                  p_A + p_B - p_A*p_B
Dependent (without replacement):        P(2nd = X | 1st = Y) changes; draw from deck of N with K good: K/N, then (K-1)/(N-1)...
```

Key intuitions:
- **Independent events have no memory.** A 5% drop after 40 failures is still 5%. Players believe otherwise (gambler's fallacy) and also believe streaks are suspicious. Players *notice runs*: in 100 coin flips the longest streak is typically about 6-7 (a standard result for fair coins), which feels "rigged" to them.
- **"1% chance" does not mean "1 in 100 guaranteed".** The chance of *not* getting a 1% drop in 100 tries is `0.99^100 = 36.6%`. In 230 tries it is still 10%. Use the `odds` command to quote this honestly in design docs and store disclosures.
- **Median vs mean.** For a geometric wait with p = 1%, the mean is 100 tries but the median is 69 and the 90th percentile is 230. Design for the **tail** (the unlucky 10%), not the mean: they are the ones who quit or complain.
- **Dependent draws** (decks, loot without replacement) reduce variance relative to independent rolls. Shuffled decks are a variance-control tool.
- **Many small rolls vs one big roll** with the same EV: the many-roll version has lower relative variance (std dev grows with sqrt(n), mean with n). Use many small rolls for stability, one big roll for drama.
- **Critical hit systems**: crit EV multiplier is `1 + c*(m-1)`. Crits with 5% chance and 2x multiplier give +5% damage but high perceived spikes. Variance per hit is `c*(1-c)*(m-1)^2*dmg^2`.
- **Accuracy and RNG in tactics games** (XCOM): a miss at a displayed 90% hit chance feels worse than the equivalent 10% event framed as a hit. Players misread displayed percentages and remember misses at high displayed odds as "rigged" (heuristic from playtesting experience); consider showing fewer extreme values, or give the player rolls that are slightly kinder than displayed, and disclose the policy.

Worked example, loot table: boss drops 1 of {Common 70%, Rare 25%, Epic 4.5%, Legendary 0.5%} with values {1, 5, 25, 200}. 
`EV = 0.7*1 + 0.25*5 + 0.045*25 + 0.005*200 = 0.7 + 1.25 + 1.125 + 1.0 = 4.075`. 
The Legendary supplies 24.5% of the value from 0.5% of the drops, which makes outcomes extremely variable. Probability of seeing at least one Legendary in 20 kills: `1 - 0.995^20 = 9.5%`. In 100 kills: `39.4%`. To give 90% of players one Legendary within the intended 40 kills, the rate must satisfy `1 - (1-p)^40 >= 0.9`, so `p >= 5.6%` (or add pity, section 6).

## 6. Managing Randomness: PRD, Pity, Shuffle Bags

Pure independent randomness produces long streaks that feel unfair (and occasionally ruin competitive matches). Tools, from least to most intrusive:

| Tool | How it works | Typical use |
|---|---|---|
| Shuffle bag | Put N items in a bag, draw without replacement, refill when empty | Tetris-style 7-bag piece sequencing, enemy spawn types, tips |
| PRD (pseudo-random distribution) | Probability grows each failure until a success, then resets | Proc effects (crit, bash, evade) in Dota 2 |
| Soft pity | Chance ramps up past a threshold | Gacha rates in many games |
| Hard pity | Guaranteed success at attempt N | Gacha, crafting, drops |
| Bad-luck protection (BLP) | Accumulates hidden progress per failure | Loot-heavy RPGs |
| Fixed schedule | Every Nth event succeeds | Predictable rewards, combos |

### 6.1 Shuffle bag

```python
import random
class ShuffleBag:
    def __init__(self, items):
        self.items = list(items); self.bag = []
    def next(self):
        if not self.bag:
            self.bag = self.items[:]; random.shuffle(self.bag)
        return self.bag.pop()
```
Properties: maximum gap between identical items is bounded by `2*N - 2`; ratios are exact over each bag. Tetris-guideline generators use a 7-bag (a documented standard). Pitfall: with small bags, **the end of a bag is predictable**; hide it or use larger/overlapping bags.

### 6.2 Pseudo-random distribution (PRD), Dota 2 style

Idea: the n-th consecutive failed attempt has success chance `P(n) = C * n`. The constant `C` is chosen so the long-run proc rate equals the nominal probability `p`.

```
P(N)    = min(1, C * N)            # N = attempts since last success (1-based)
E[tries]= sum_{k>=0} P(no success in first k tries) = 1/p      # solve for C by bisection
```

Known constants (computed with `design_calc.py prd`; they match the widely published Dota 2 table):

| Nominal p | C | Guaranteed by attempt |
|---|---|---|
| 5% | 0.003802 | 264 |
| 10% | 0.014746 | 68 |
| 20% | 0.055704 | 18 |
| 25% | 0.084744 | 12 |
| 30% | 0.118949 | 9 |

Effect of PRD at p = 25%: the longest failure streak in 200,000 simulated attempts was 10, versus 37 for pure random (seeded simulation). Early attempts have a **lower** chance than 25% (8.5% on the first attempt), so PRD reduces both bad and good streaks: it also makes "two procs in a row" rarer, which suppresses lucky outliers in competitive play. Use PRD when you want **fair, low-variance** procs in PvP; avoid it where players need the thrill of rare lucky spikes.

How to apply: store a per-source counter; on each attempt increment `N`, roll against `C*N`; reset `N` on success. Show the nominal chance in the UI (the tooltip says 25%), and document that the effective short-term chance varies.

### 6.3 Pity timers (gacha and loot)

```
p_n = base_p                                 for n < soft_start
p_n = min(1, base_p + (n - soft_start + 1) * step)   for soft_start <= n < hard
p_n = 1                                       for n = hard                   # hard pity
E[pulls] = sum_{n=1..hard} n * p_n * prod_{k<n}(1 - p_k)
```

Worked example (a design commonly described by players of a popular gacha: 0.6% base, soft pity from pull 74, hard pity at 90; the public rate is the 0.6% and the 90 guarantee, while the ramp shape is community-measured, so treat it as an illustration):

| Setup | Expected pulls to first top-rarity | 50% / 90% / 99% pulls |
|---|---|---|
| No pity (0.6%) | 166.7 | 116 / 383 / 766 (geometric) |
| Hard pity at 90 only | 69.7 | 90 / 90 / 90 |
| Hard 90 + soft ramp from 74 (+6 points per pull) | 62.3 | 76 / 80 / 83 |

Observations:
- The **effective rate** (1/62.3 = 1.6%) is about 2.7x the advertised base rate; "advertised rate" and "effective rate" differ greatly with pity. Regulators in several jurisdictions require disclosing probability (see `references/09-monetization-and-live-ops.md`); disclose both numbers.
- Soft pity compresses the distribution: the 99th percentile drops from 766 to 83 pulls. It is a **retention and trust tool**: it removes the worst-case tail that makes players churn or complain.
- If there is a **50/50 featured-item rule** on top of pity (lose the 50/50, then the next top-rarity is guaranteed featured), expected cost to a specific item becomes `E = E1 * (1 + (1 - q))` with q the win chance, and the 99th percentile roughly doubles. Model it before launch.
- Carry-over pity across banners is a player-friendly, heavily appreciated feature.

Ethics: a pity system is a fairness feature, but it can also be used to anchor spending ("you are 10 pulls from guaranteed"). Cost transparency and spend caps are discussed in the monetization reference.

## 7. Progression Curves

Pick the curve by what you want the player to feel, then inspect the **ratio between consecutive levels** (`xp[L+1]/xp[L]`) and the **time-per-level**, not just the formula.

| Curve | Per-level cost | Total to reach L | Feel | Use |
|---|---|---|---|---|
| Linear | `a + b*L` | quadratic in L | Steady, little deceleration | Short games, skill-tree points |
| Polynomial | `a * L^k` (k=2..3) | `~ a*L^(k+1)/(k+1)` | Gentle slowdown, long reachable cap | Most RPGs, Pokemon-style |
| Exponential | `a * g^L` (g=1.05..1.3) | `a*(g^L - 1)/(g - 1)` | Strong slowdown, "walls" appear; prestige friendly | Idle games, MMOs with long-tail caps |
| Logistic (S-curve) | `cap / (1 + e^{-k(L - mid)})` | S-shaped | Fast start, slow middle, plateau at cap | Per-level cost that stabilizes; fast intro then grind then ease |
| Piecewise | Different formulas per level range | | Hand-tuned pacing | Almost all shipped games in practice |

### 7.1 Real XP formulas

| Game | Formula (verified in this skill's calculations) | Notes |
|---|---|---|
| Old School RuneScape | `xp(L) = floor( (1/4) * sum_{x=1}^{L-1} floor(x + 300 * 2^(x/7)) )` | Level 99 = 13,034,431 XP; level 92 is about half of that (6,517,253). Exponential: +10% XP per level approx, doubles every 7 levels (OSRS Wiki) |
| Pokemon (Medium Fast group) | `xp(n) = n^3` | Level 100 = 1,000,000 |
| Pokemon (Fast) | `xp(n) = 4n^3/5` | Level 100 = 800,000 |
| Pokemon (Medium Slow) | `xp(n) = 6n^3/5 - 15n^2 + 100n - 140` | Level 100 = 1,059,860 |
| Pokemon (Slow) | `xp(n) = 5n^3/4` | Level 100 = 1,250,000 |
| D&D 5e (SRD thresholds) | Hand table: L2 300, L5 6,500, L10 64,000, L20 355,000 | Piecewise; steep early, heavy late |

Pokemon values come from the commonly published experience-group formulas (Bulbapedia, which blocks automated checking); the numbers were recomputed from the formulas. D&D thresholds are from the 5e SRD.

### 7.2 Design the curve from time targets

Work backward:
1. Choose **target hours** to reach milestones (e.g. level 10 in 2 h, 30 in 15 h, cap in 60 h).
2. Estimate **XP/hour** at each stage (sources: quests, kills, activities).
3. Compute required `XP(level)` = XP/hour x hours per level; fit a curve through those points.
4. **Smooth** with a function; then adjust so there are no dead levels (a level that takes 5x longer than its neighbors without a content gate).

Example: reach level 20 in 10 hours with a per-level exponential curve. With XP/hour that scales as `r(L) = 1000 * 1.08^L` (content pays more later), per-level time target 0.5 h: `cost(L) = 500 * 1.08^L`. The calculator can print the table: `curve --type exp --base 500 --growth 1.08 --levels 20 --xp-per-hour 2000`.

Rules:
- **Fast early levels** (1-5 in minutes) give instant reward and teach the system; slow late levels keep long-term goals.
- Keep **power gains per level** proportional to cost, or the player will feel level 40 -> 41 is meaningless. If cost rises 15% per level, either raise rewards or space them (level-ups every N levels grant bigger rewards).
- **Horizontal vs vertical power**: later levels should add options (skills, builds) more than raw numbers, or the curve becomes a treadmill.
- **Number inflation**: every multiplier on the player side demands one on the enemy side. Ideal: enemy HP and damage derive from a single `level_scale(L)` function; items derive from the same function (single source of truth, section 8).
- **Soft caps / diminishing returns**: `effective = stat / (stat + K)` gives smooth saturation; hard caps create dead stat points.
- **Catch-up XP** for late joiners/alts (rested XP, bonus for lower level) addresses multiplayer fragmentation.

## 8. Spreadsheet-Driven Balancing

A spreadsheet (Sheets/Excel/Airtable) is the first balance tool for 90% of games, and the data source the game imports.

Structure (recommended):
1. **Parameters sheet** - named global constants (`level_scale`, `crit_mult`, `K_armor`).
2. **Entities sheet** - one row per unit/item/card with raw inputs only (cost, base stats, tags).
3. **Derived sheet** - formulas: DPS, EHP, TTK vs reference enemy, cost-per-power, rank vs curve.
4. **Matchups sheet** - matrix of pairwise TTK or win probability (intransitive checks).
5. **Progression sheet** - level, XP, cumulative XP, expected time at target XP/hour, power per level.
6. **Economy sheet** - sources/sinks per hour, balance over time (section 12).
7. **Checks sheet** - assertions that flag outliers (cost per power outside band, TTK outside range, monotonicity violations) with conditional formatting.

Practices:
- **No hard-coded numbers in formulas**; reference named cells.
- **Inputs vs outputs color coding** (blue input, black formula is a common finance convention that works here).
- Add a **reference opponent / reference player** (a "standard" enemy or character at each level) so values mean something.
- Version the sheet; export to CSV/JSON on each commit so the game loads data, not code. Designers can then iterate without engineers.
- Spreadsheets cannot model **adaptive behavior**. When behavior matters (AI, player decisions, cooldown rotations), simulate (section 9).
- Include **scenario columns**: casual player, average, expert; best-case and worst-case gear; solo and group.

## 9. Simulation and Monte Carlo

Use a script when the sheet cannot express stochastic or sequential behavior.

When to simulate:
- Variance matters (fight outcomes, drop streaks, crit chains).
- Behavior depends on state (cooldowns, resource management, AI choice).
- Many items interact (full card collections, random builds).
- You need **distributions**, not means (time to complete, bankroll over time, gold at hour 10).

Pattern:

```python
import random, statistics
def fight(a, b, rng):
    ha, hb, t = a["hp"], b["hp"], 0.0
    na = nb = 0.0                                   # next attack time
    while ha > 0 and hb > 0 and t < 120:
        if na <= nb:
            t = na; na += 1/a["rate"]
            if rng.random() < a["acc"]: hb -= a["dmg"] * (2 if rng.random() < a["crit"] else 1)
        else:
            t = nb; nb += 1/b["rate"]
            if rng.random() < b["acc"]: ha -= b["dmg"] * (2 if rng.random() < b["crit"] else 1)
    return ha > 0
rng = random.Random(7)
wins = sum(fight(A, B, rng) for _ in range(20000)) / 20000
```

Guidance:
- **Seed the RNG** for reproducible results; log the seed.
- **Number of runs**: standard error of a win rate is `sqrt(p*(1-p)/n)`. For ±1 percent (at 95% confidence, ~2 standard errors) near p = 0.5 you need `n ~ 10,000`. For ±0.5 percent: ~40,000.
- **Run sweeps**: vary one parameter across a range and plot output (win rate vs damage; time-to-cap vs XP rate). Look for cliffs and plateaus.
- **Round-robin** all pairs of heroes/decks/builds for a matchup matrix; compute overall win rate and flag outliers outside 45-55% (heuristic band).
- **Strategy search**: for builds, use hill climbing or random sampling to find the strongest (the "solved" build). If the best build is far above the median, there is a dominance problem.
- **Bot players** of differing skill (random, greedy, lookahead) show whether skill matters. If a random bot wins 45% against a greedy one, the game may be too luck-driven.
- **Economy simulation**: simulate N virtual players with distributions of play time and decisions; track total currency in circulation, price indexes, and the Gini coefficient.
- Verify the simulation against **analytic cases** (e.g. a known probability) before trusting it for the unknown.
- A simulation shows what *your model* does; validate with real telemetry (see `references/12-playtesting-and-analytics.md`).

## 10. Metagame Balancing with Pick and Win Rates

For live competitive games, data decides; instincts propose.

Core metrics:
| Metric | Definition | Reading |
|---|---|---|
| Pick rate | Share of matches (or of picks available) where the option is chosen | High = popular (fun or strong) |
| Win rate | Wins / games | ~50% target in symmetric games |
| Ban rate | Share of matches where the option is banned | High = feared / frustrating |
| Presence | Pick + ban | Overall influence |
| Win rate by skill bracket | Win rate split across ratings | Reveals "easy to use" (strong at low skill) vs "high skill ceiling" |
| Win rate by match length / patch age | Reveals scaling and meta shifts | |
| Matchup matrix | Win rate of A vs B | Intransitive structure |

Interpretation matrix (heuristic):

| Pick rate | Win rate | Likely state | Typical action |
|---|---|---|---|
| High | High | Overpowered | Nerf (small), or buff competitors |
| High | ~50% | Popular, balanced (often fun or low-barrier) | Leave alone |
| High | Low | Seductive trap / flashy but weak or hard | Check skill-bracket split; buff or educate |
| Low | High | Hidden gem / hard to use / niche | Leave alone; maybe buff learning aids |
| Low | Low | Weak | Buff |

Pitfalls and fixes:
- **Sample size.** Always report a confidence interval. For win rate `w` in `n` games, the Wilson interval is more reliable than normal approximation near extremes:

```
center = (p + z^2/(2n)) / (1 + z^2/n)
margin = z * sqrt( p(1-p)/n + z^2/(4n^2) ) / (1 + z^2/n)         (z = 1.96 for 95%)
```
Example: 520 wins in 1,000 games -> 48.9% to 55.1% (could be fair). 5,200 in 10,000 -> 51.0% to 53.0% (statistically above 50%, so a real +2 point edge).
- **Selection bias.** Strong players pick strong options; a character's win rate reflects who plays it. Correct by conditioning on rating, and on opponent and ally strength (regression, or compare with mirror matchups).
- **Counter-pick bias.** Options chosen in response to a pick skew the win rate (flex picks).
- **Meta feedback.** A nerf of the strongest option moves the player base to the next strongest; nerfing one at a time is a treadmill. Raise the floor (buff the weakest) when multiple options sit below band.
- **Data vs perception.** Frustration rating is not win rate: a "fair" 52% character with unavoidable stun-lock can be more hated than a 57% character with clear counterplay. Track *ban rate* and survey/forums, not just the win rate.
- **Elo/Glicko/TrueSkill** adjust for strength of schedule; see `references/10-multiplayer-and-social.md` for matchmaking details.
- **Time-lag.** Patch -> metagame adapts over 1-2 weeks; evaluate after the shift, not the first day.

## 11. Nerf and Buff Philosophy

Principles used by experienced live teams (practice and heuristics unless noted):

1. **Prefer buffs to nerfs** when you have a choice. Players enjoy gains and remember losses (loss aversion). Raising weak options lifts the whole field without taking anything away. But beware **power creep**: always buffing breaks the relation to enemies/content.
2. **Nerf the cause, not the symptom.** If a hero is overpowered because of one ability, nerf that ability, not the base stats (which hurts every other use of the hero).
3. **Change one variable at a time**, and log the change, so the next data point has an interpretable cause.
4. **Move numbers by noticeable but modest amounts.** A change under ~5% in a stat is often invisible in play (heuristic); 10-20% is usually perceived; big swings (50%+) risk overcorrection. Prefer to iterate again in two weeks rather than overshoot.
5. **Change the shape, not just the number**, when the problem is structural (a dominant strategy because it has no counterplay). Number tweaks alone cannot fix it.
6. **Preserve identity.** The thing players loved about the option must survive the nerf (a nerf that deletes the fantasy is a delete).
7. **Communicate.** Patch notes with reasons ("X was winning 56% and was chosen in 40% of games, so we reduced Y by 10%") build trust. Hidden changes ("stealth nerfs") destroy it.
8. **Respect purchased content.** If players paid (skins, characters, cards), nerfing is a trust issue; prefer buffs to alternatives, or provide refunds/crafting compensation when nerfing paid items (see monetization reference).
9. **Slow, regular cadence** beats rare, big patches in competitive games; tournaments need frozen "balance windows."
10. **Test inside the studio first.** Internal players should find the dominant strategy before release, using the simulation tools of sections 9-10.

Case study (Halo 3 sniper rifle; Griesemer 2010): the GDC talk is titled for a change of the sniper rifle's time between shots from 0.5 to 0.7 seconds (a 40% longer interval) and discusses the sandbox reasoning behind weapon roles. Take-away: a single timing parameter can change the entire role of a weapon, so expect first-order and second-order effects (watch the talk for the details; I am not quoting its contents).

Anti-patterns: nerf-hammer cycles (every patch nerfs the top pick), "flavor of the month" balance by rotation, balancing around the top 0.1% when the player base is mostly casual (or vice versa), and ignoring the *feel* of an ability (a 5% damage nerf is acceptable; a hit-feel nerf may not be).

## 12. Virtual Economies

### 12.1 Faucets, sinks, inflation

An economy is a **flow system**: resources enter through *faucets* (quests, drops, rewards, daily bonuses), leave through *sinks* (repairs, fees, consumables, upgrades), and accumulate in player *stocks*.

```
d(supply)/dt = faucets - sinks
inflation (price level) rises when supply of money grows faster than supply of goods
Target:   sinks ~= faucets over a typical lifecycle (net faucet slightly positive early, balanced late)
```

Checklist:
- Draw a **resource flow diagram** (Machinations-style, Adams and Dormans 2012): sources, converters, drains, pools, with rates.
- Count **all** faucets, including the invisible ones (selling to NPC vendors, event rewards, store refunds, bugs/dupes).
- Count **all** sinks: repair costs, taxes/fees (auction fees), consumables, upgrade costs, cosmetics, level-based "gold sinks", inactivity decay, permanent removals (item destruction).
- Distinguish **item sinks** (removing goods) from **currency sinks** (removing money). A currency-only sink does not solve glut of goods.
- **Per-player velocity.** Track currency earned/spent per player per hour by cohort. Long-time players with large stockpiles and new players have very different realities; "average gold" is a misleading statistic (use medians and a Gini coefficient).
- **Gini coefficient** of wealth: 0 = equal, 1 = one player holds everything. Real MMOs typically show high inequality (heuristic); watch the trend, not an absolute target.
- **Inflation fixes:** add sinks that scale with wealth (percentage-based fees/taxes), lifetime-priced prestige items (high-end cosmetics, housing), convert gold to permanent goods, limit faucet scaling, soft-cap earning (diminishing returns), reset-based economies (seasonal leagues, roguelike runs).
- **Deflation** is also a problem: if sinks exceed faucets, prices drop, players feel poor, and the economy freezes.
- **Bot and dupe risk**: model what happens with 10x faster earning than designed. If it breaks the economy, add safeguards.

Worked example: dungeon crawler. Faucets: average 120 gold/hour from drops + 80 from quests = 200 gold/hour. Sinks: repair costs 15% of earned gold (30/h), potions average 25/h, auction fee 5% on sales. Vendor price of next upgrade: 2,000 gold, intended purchase cadence once per 10 hours of play. Net accumulation = 200 - 30 - 25 = 145/h, 1,450 per 10 h, short of 2,000 by 550. Either the upgrade costs 1,450 (cadence matches) or faucets are reduced. **Check both**: if cadence is fine for the average player, the top 10% (earning 2x) will buy upgrades every 5 h and exhaust content. Add a stage cost multiplier (cost grows 15% per purchase) to stretch it.

### 12.2 Currencies: hard, soft, and more

| Type | Obtained by | Role | Notes |
|---|---|---|---|
| Soft currency | Gameplay | Everyday spending | Must have strong sinks |
| Hard / premium currency | Real money (and sometimes gameplay trickle) | Convenience, cosmetics, time skips | Obfuscates real prices (see `09`); regulated in places |
| Event / seasonal currency | Limited-time play | Drives events; expires | Prevents hoarding |
| Reputation / faction tokens | Specific activities | Gates content | Non-tradable |
| Account-bound vs tradable | | Controls market, RMT risk | Bound goods keep economy contained |
| Time (energy, stamina) | Regenerates | Pacing | Not money, but behaves like a capped faucet |

Rules:
- **One conversion path** between soft and hard currency, with clearly defined direction (hard -> soft, avoid soft -> hard unless in a player market with fees).
- **Currency count budget**: every additional currency adds cognitive load; justify each with a distinct sink and source (heuristic: 2-4 for most games).
- **Expiration** or **caps** limit hoarding, but expiring currency feels punitive; use caps with a visible meter and a generous grace.
- **Fractional/decimal** values hide inflation poorly; choose units so common purchases are 2-4 digits.

### 12.3 Trading and auction houses

- **Pros of player trading:** social interaction, emergent professions, market economy, item "liquidity" that makes drops matter.
- **Cons:** RMT (real money trading), gold-selling bots, scams, market manipulation, trivializing loot, making drops "boring" because the efficient move is selling for gold.
- **Auction house design levers:** listing fee (sink), sales tax (sink), duration, minimum price, tradable limits per day, bind-on-pickup for top gear, max active listings, price-history display. Fees with percent-based sinks scale with wealth.
- **Diablo III** is the usual cautionary tale: it launched in 2012 with gold and real-money auction houses; Blizzard shut both down in 2014 and shipped a loot overhaul with its Reaper of Souls expansion (Wikipedia, Diablo III), because trading drove players to buy instead of play and made drops feel worthless. Lesson: in loot-driven games, trading changes the *meaning* of play.
- **Alternatives:** direct trading with limits, bartering (Path of Exile has no gold-based auction house, by design), account-bound with "trade tokens", gifting, seasonal ladders.
- **Market information** (price history, volume) helps new players avoid scams and stabilizes prices, but also lets bots optimize. Provide it with rate limits.

### 12.4 Lessons from EVE, Ultima Online and Castronova

**EVE Online.** A fully player-driven economy (industry, mining, trading, war), where almost all items are player-made and destroyed in combat. Notable facts: CCP hired an in-house economist in 2007, the first game developer to do so (Wikipedia, Eve Online); the studio has published player-facing economic reports (check the official EVE site for the current location). Destruction of ships in war is the main **sink**; the 2014 Battle of B-R5RB destroyed assets that press outlets valued at up to about $330,000 in real-world terms (Polygon via Wikipedia). Lessons:
1. **Destruction is a feature.** Item sinks through combat make demand for production permanent.
2. **Hire or consult an economist;** treat the economy as a system under continuous observation, publish data.
3. **Risk and reward are tied to location** (low-security vs high-security space), so prices reflect risk.
4. **Player institutions** (alliances, banks, scams) emerge; scams are part of the game by design, but they set the trust threshold of the wider community.
5. **Time-scarce commodity** (skill training in real time) is a distinctive sink/limiter.

**Ultima Online.** An early (1997) large-scale persistent world. Raph Koster, a lead designer, documented that the initial ecology simulation (predators and prey with population dynamics) was overwhelmed by player behavior: players killed animals faster than they could repopulate, and ecological ambitions were scaled back (Koster, "Laws of Online World Design" and talks; consult the source for details). Lesson: **players optimize for their own goals, not the designers' simulation intent**; simulated systems must be robust to extreme, coordinated behavior. (Heuristic summary; read Koster's essays for the primary claims.)

**Castronova (2001, 2005).** Economist Edward Castronova studied EverQuest's Norrath as a real economy and argued from observed auction prices that the world had a measurable gross national product per capita and a real exchange rate with the dollar (Castronova 2001, CESifo Working Paper 618, "Virtual Worlds: A First-Hand Account of Market and Society on the Cyberian Frontier"; the paper reported a per-capita GNP comparable to that of lower-middle-income countries, verify exact figures in the source before quoting). His book *Synthetic Worlds* (2005) argues virtual economies are real economies when time, scarcity and exchange exist. Practical takeaways: (1) any scarce, tradable virtual good acquires a real-money price eventually; (2) design with the assumption that RMT will exist (decide your stance: ban, tolerate, or sanctioned tokens such as WoW Token-style systems); (3) time is the fundamental currency of players; (4) economists' tools (supply, demand, elasticity, inflation) apply directly.

## 13. Crafting Economies

Crafting links gathering, markets and gear; it can be a core loop or a sink.

Design questions:
1. **Role:** is crafting the *primary* source of gear (Eve, Star Wars Galaxies, Albion) or a *supplement* to loot (Diablo, WoW professions)?
2. **Inputs / outputs:** the recipe converts inputs (raw materials) to outputs (items). Value-add: `output_value = sum(input_value) * (1 + margin) - crafting_cost`. If margin <= 0 nobody crafts; if too high, crafted goods flood.
3. **Loss ratio:** how much value disappears in conversion? A crafting step that **destroys** 10-30% of input value (heuristic) acts as a sink and keeps goods scarce.
4. **Determinism vs gambling:** deterministic recipes are predictable (good for planning); random outcomes (enchant failure, quality rolls) add excitement and act as sinks, but can create frustration; use **bad-luck protection** or partial refunds.
5. **Quality tiers:** inputs influence output quality; allow substitutes so supply shocks don't freeze the market.
6. **Recipe discovery and gating:** unlocked via skill, rarity, reputation, or experimentation. Gate by *skill*, not by exclusive supply of one rare material (single points of failure).
7. **Salvaging/recycling:** recovers some fraction of materials; keeps the junk in the loop and caps item glut. Set recovery < 100% (e.g. 30-60%, heuristic).
8. **Crafting speed/time gates:** time as a cost; ensure waiting doesn't become mandatory log-in (see `09`).
9. **Market linkage:** are materials tradable? If so, price follows the scarcity of the rarest input; make sure the rarest input has a *supply schedule*, not infinite.
10. **Dead-end items:** craft intermediate products that are useful in more than one recipe to keep demand broad.

Worked example (3-tier crafting):
```
Raw: Ore (gather: 60/h average, price 1)
Tier 1: Ingot = 3 Ore + 1 fuel(0.5)        -> cost 3.5, sells 4.0  (margin ~14%)
Tier 2: Blade = 2 Ingot + 1 Hilt(2.0)      -> cost 10.0, sells 12.0 (margin 20%)
Tier 3: Enchanted Blade = Blade + 1 Rune(8) + 20% failure chance (destroys Rune)
        expected rune cost = 8 / 0.8 = 10; total = 12 + 10 = 22 per success; sells 28 (margin 27%)
```
Check: crafter hourly income = (gather 60 Ore/h => 20 Ingots/h => 4 per Ingot margin...) Run the time-per-craft through a sheet to ensure crafting yields comparable gold/hour to the alternative (grinding monsters). **Rule: the best activity pays the least more than the next best;** no activity should be 5x more lucrative than others, or players will funnel into it (and it will crash its own market).

Pitfalls: crafting that yields only obsolete items (everyone upgrades from loot), crafting that is mandatory but boring, and single-recipe monopolies.

## 14. Idle and Incremental Math

Idle games (Cookie Clicker, AdVenture Capitalist) run on exponential growth in cost and production (Pecorella 2015; Wikipedia, Incremental game).

Core formulas:

```
cost(n)          = base_cost * g^n                      # price of the (n+1)-th unit; g = 1.07-1.15 typical
cost to buy k    = base_cost * g^n * (g^k - 1) / (g - 1)  # geometric series
max affordable k = floor( log( 1 + gold*(g-1) / (base_cost * g^n) ) / log(g) )
production(n)    = n * rate * multipliers
payback time     = cost(n) / (rate * multipliers)          # in seconds; core pacing number
```

Cookie Clicker-style growth `g = 1.15`: buying 10 units multiplies the unit price by `1.15^10 = 4.05`. Doubling the production rate every ~5 purchases (`1.15^5 = 2.01`) keeps the payback time roughly constant, which is the target (payback ~ the length of the idle break you want). Per-building efficiency decays across the same tier; new building tiers (cost x10-x100, rate x~8-10) create "reset" moments.

Design rules:
1. **Cost grows slightly faster than production per unit** so the player is always gated by time, never fully free. If production per unit grows at least as quickly as cost (g_cost <= g_prod), growth is unlimited; check this ratio.
2. **Multipliers** (upgrades) are the "pop." Place them to arrive when payback times stretch; each should be a 2x-ish jump, felt (heuristic).
3. **Prestige (reset) loop**: reset progress for a permanent multiplier. Common formula: `prestige_currency = floor( (lifetime_earnings / K)^(1/2 or 1/3) )`; the root makes the reward grow slowly, so players choose *when* to reset. Check that the first reset arrives in ~1-2 hours and each next reset after ~2-3x longer (heuristic).
4. **Offline progress**: awards `production * time * offline_factor` (often 0.1-1.0 with a cap in hours); keep the offline factor < 1 so active play has value.
5. **Big-number display**: use scientific/engineering notation, abbreviations (K, M, B, T, aa, ab...). Numbers beyond 1e308 overflow doubles; use a big-number library or log representations if the design needs them.
6. **Time-to-milestone planning**: simulate the optimal buy order; ensure no stall > the intended wait (e.g., no more than 5-10 minutes of nothing to buy early).
7. **Meaningful decisions** beyond "click buy": branching upgrades, limited choice (ascension perks), trade-offs between active and passive play.
8. **Ethical note:** idle games with monetized time-skips need care to avoid exploiting players (see `09`).

Example prestige check: lifetime earnings 1e9, K = 1e6, cube root: `(1e9/1e6)^(1/3) = 1000^(1/3) = 10` prestige points; at 8e9: `(8000)^(1/3) = 20`. Doubling prestige currency takes 8x earnings: a natural "grow in a few cycles" curve.

## 15. Calculator

`scripts/design_calc.py` is a dependency-free Python 3 CLI. Run `python scripts/design_calc.py --help` or `python scripts/design_calc.py <command> --help`. Commands: `curve`, `ev`, `odds`, `pity`, `prd`, `ttk`. Outputs below were produced by running the script (Python 3.15 on Windows); randomness is seeded.

**curve** - level to XP table (linear / poly / exp / logistic):
```
$ python scripts/design_calc.py curve --type exp --levels 10 --base 100 --growth 1.15
 Level     XP to next    Cumulative XP     Ratio
     1            100                0         -
     2            115              100     1.150
     ...
    10            352            1,679     1.150
Total XP to reach level 10: 1,679
$ python scripts/design_calc.py curve --type poly --levels 8 --base 50 --exponent 2 --xp-per-hour 2000
Total XP to reach level 8: 7,000
At 2000.0 XP/hour: 3.5 hours to level 8
```
(Note: the first level's cumulative is 0; the XP column is the cost to go from L to L+1.)

**ev** - expected value of a loot table:
```
$ python scripts/design_calc.py ev 100:0.01 10:0.2 1:0.5 --cost 5
Note: probabilities sum to 0.7100; remaining 0.2900 treated as value 0.0 (--rest).
Expected value per roll : 3.5000
Variance / std dev      : 108.2500 / 10.4043
Cost per roll           : 5.0000  -> net EV -1.5000, return 70.0%
```

**odds** - at-least-one and confidence:
```
$ python scripts/design_calc.py odds --p 0.02 --n 50 --confidence 50 90 99
P(at least 1 success in 50 tries at p=0.02) = 63.5830%
P(zero successes)                          = 36.4170%
Mean tries to first success (1/p)          = 50.00
   50.0% -> 35 tries
   90.0% -> 114 tries
   99.0% -> 228 tries
```

**pity** - exact expectation by DP, optional Monte Carlo cross-check:
```
$ python scripts/design_calc.py pity --p 0.006 --hard 90 --soft-start 74 --soft-inc 0.06 --sim 100000
Expected pulls per success      : 62.30  (no pity: 166.67)
Effective rate (1/expected)     : 1.6052%
Pulls for 50% confidence        : 76
Pulls for 90% confidence        : 80
Pulls for 99% confidence        : 83
Monte Carlo (100000 runs)        : mean 62.34 pulls, max seen 88
$ python scripts/design_calc.py pity --p 0.006 --hard 90
Expected pulls per success      : 69.70  (no pity: 166.67)
```

**prd** - Dota-style constant C:
```
$ python scripts/design_calc.py prd --p 0.25 --sim 200000
Nominal p = 0.2500 -> C = 0.084744   (P on attempt N = C*N; guaranteed by attempt 12)
   simulated 200000 trials: observed rate 0.2498, longest failure streak 10
   pure random streak for comparison: longest failure streak 37
$ python scripts/design_calc.py prd --p 5 10 20 30 --percent     # C = 0.003802, 0.014746, 0.055704, 0.118949
```

**ttk** - time to kill:
```
$ python scripts/design_calc.py ttk --hp 100 --damage 24 --fire-rate 8 --accuracy 0.7 --crit 0.1 --crit-mult 2 --armor 30 --sim 20000
Damage per hit after armor     : 18.46  (raw 24.00, mode ratio)
Effective DPS (acc+crit)       : 113.72
Shots to kill, best case       : 3  (all hits are crits)
Shots to kill, no crits        : 6  (all hit)
TTK best / no-crit / expected  : 0.250s / 0.625s / 0.875s  (first shot at t=0)
Monte Carlo (20000 runs) TTK       : mean 0.866s, p50 0.875s, p90 1.250s, p99 1.625s
```
Reading it: the p99 TTK (1.625 s) is nearly double the median; a 30-armor target stretches the weapon from 0.625 s expected TTK with no armor (5.41 expected shots, rounded up to 6 shots at 8 shots/s: 5/8 s) to 0.875 s (30 armor: 7.03 expected shots, rounded up to 8: 7/8 s); tune against the *p90*, not the mean.

## 16. Checklists and Pitfalls

**Balance review checklist**
- [ ] Is there a written balance goal (target win rate, clear rate, time-to-X)?
- [ ] Are all numbers in one data source, with derived columns?
- [ ] Has every option been scored on the cost curve, and outliers explained?
- [ ] Do TTK/EHP values have min and max bounds across all matchups, in both directions?
- [ ] Are random systems quantified at the 50/90/99th percentile, not only the mean?
- [ ] Is there a counter or answer to every strong option (information + commitment)?
- [ ] Do multiplicative stacks have caps or diminishing returns?
- [ ] Is the economy modeled with faucet and sink per hour for casual / average / hardcore?
- [ ] Is there a plan for inflation, bots/dupes, and RMT?
- [ ] Are metrics reported with sample size and intervals?
- [ ] Is the change log recording what was changed, why, and the expected effect?

**Common pitfalls**
| Pitfall | Why it hurts | Fix |
|---|---|---|
| Balancing for the average of a bimodal player base | Satisfies nobody | Segment by skill/time-played |
| Over-reliance on win rate | Ignores frustration, fun | Add ban rate, retention, surveys |
| Linear costs for super-linear power | Late items dominate | Recompute value in DPS/EHP terms |
| Hidden breakpoints | Wasted stats | Expose or smooth |
| Currency-only sinks | Goods glut | Add item sinks |
| Fixed-price sinks in an inflating economy | Sinks become trivial | Percentage-based fees |
| Trusting averages | Heavy tails dominate experience | Use percentiles |
| Tuning during playtests with the designer playing | Designer skill bias | Use naive players and bots |
| Changing many variables | Cannot attribute effects | One variable per iteration |
| Trusting a simulation without validation | Model error | Compare to telemetry |

## 17. References

Inline citations use (Author Year). See references/13-bibliography.md for the master list.

**Books**
- Schreiber, I. and Romero, B., 2021, *Game Balance*, CRC Press (ISBN 978-1498799577).
- Adams, E. and Dormans, J., 2012, *Game Mechanics: Advanced Game Design*, New Riders (ISBN 978-0321820273).
- Castronova, E., 2005, *Synthetic Worlds: The Business and Culture of Online Games*, University of Chicago Press (ISBN 978-0226096278).
- Schell, J., 2019, *The Art of Game Design: A Book of Lenses*, 3rd ed., CRC Press.
- Koster, R., 2004, *A Theory of Fun for Game Design*, Paraglyph Press.

**Papers**
- Castronova, E., 2001, "Virtual Worlds: A First-Hand Account of Market and Society on the Cyberian Frontier", CESifo Working Paper No. 618, SSRN: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=294828 (SSRN blocks automated access; the identifier was verified through Crossref, DOI 10.2139/ssrn.294828).

**Talks**
- Griesemer, J., 2010, "Design in Detail: Changing the Time Between Shots for the Sniper Rifle from 0.5 to 0.7 Seconds for Halo 3", GDC, https://www.gdcvault.com/play/1012211/Changing-the-Time-Between-Shots

**Websites**
- Schreiber, I., 2010, *Game Balance Concepts* (online course): https://gamebalanceconcepts.wordpress.com/
  - Level 3, Transitive Mechanics and Cost Curves: https://gamebalanceconcepts.wordpress.com/2010/07/21/level-3-transitive-mechanics-and-cost-curves/
  - Level 4, Probability and Randomness: https://gamebalanceconcepts.wordpress.com/2010/07/28/level-4-probability-and-randomness/
  - Level 5, Probability and Randomness Gone Horribly Wrong: https://gamebalanceconcepts.wordpress.com/2010/08/04/level-5-probability-and-randomness-gone-horribly-wrong/
  - Level 7, Advancement, Progression and Pacing: https://gamebalanceconcepts.wordpress.com/2010/08/18/level-7-advancement-progression-and-pacing/
  - Level 8, Metrics and Statistics: https://gamebalanceconcepts.wordpress.com/2010/08/25/level-8-metrics-and-statistics/
  - Level 9, Intransitive Mechanics: https://gamebalanceconcepts.wordpress.com/2010/09/01/level-9-intransitive-mechanics/
- Old School RuneScape Wiki, "Experience": https://oldschool.runescape.wiki/w/Experience
- Wikipedia, "Incremental game": https://en.wikipedia.org/wiki/Incremental_game
- Wikipedia, "Eve Online": https://en.wikipedia.org/wiki/Eve_Online
- Wikipedia, "Ultima Online": https://en.wikipedia.org/wiki/Ultima_Online
- Wikipedia, "Diablo III" (auction house history): https://en.wikipedia.org/wiki/Diablo_III
- Wikipedia, "Virtual economy": https://en.wikipedia.org/wiki/Virtual_economy
- Wikipedia, "Gini coefficient": https://en.wikipedia.org/wiki/Gini_coefficient
- Wikipedia, "Binomial distribution": https://en.wikipedia.org/wiki/Binomial_distribution
- Wikipedia, "Monte Carlo method": https://en.wikipedia.org/wiki/Monte_Carlo_method
- Koster, R., "Laws of Online World Design": https://www.raphkoster.com/games/laws-of-online-world-design/
- Pecorella, A., 2015, "The Math of Idle Games", Kongregate Developers Blog (original URL no longer resolves; cited for the cost-growth model, not linked).
- Dota 2 "Random Distribution" community wiki pages (blocked to automated access); the constants in section 6.2 were recomputed with `scripts/design_calc.py prd`.
