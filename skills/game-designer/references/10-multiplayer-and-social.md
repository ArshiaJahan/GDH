# Multiplayer and Social Design

Designing games for more than one human: modes, competitive structure, matchmaking and rating, team roles, netcode-aware design, cooperation, social systems, toxicity and prosocial design, cheating, community/UGC, population health and cross-play.

## Table of Contents

1. [How to Use This File](#1-how-to-use-this-file)
2. [Multiplayer Modes](#2-multiplayer-modes)
   - [2.1 Mode overview](#21-mode-overview)
   - [2.2 PvP formats](#22-pvp-formats)
   - [2.3 PvE co-op](#23-pve-co-op)
   - [2.4 Asymmetric multiplayer](#24-asymmetric-multiplayer)
   - [2.5 MMO and persistent worlds](#25-mmo-and-persistent-worlds)
   - [2.6 Asynchronous multiplayer](#26-asynchronous-multiplayer)
   - [2.7 Local and couch play](#27-local-and-couch-play)
3. [Designing for Competitive Play](#3-designing-for-competitive-play)
   - [3.1 Skill expression](#31-skill-expression)
   - [3.2 Counterplay](#32-counterplay)
   - [3.3 Readability](#33-readability)
   - [3.4 Snowballing and comeback mechanics](#34-snowballing-and-comeback-mechanics)
   - [3.5 Randomness in competitive games](#35-randomness-in-competitive-games)
   - [3.6 Metagame and balance process](#36-metagame-and-balance-process)
   - [3.7 Esports considerations](#37-esports-considerations)
4. [Matchmaking and Rating Systems](#4-matchmaking-and-rating-systems)
   - [4.1 Elo](#41-elo)
   - [4.2 Glicko and Glicko-2](#42-glicko-and-glicko-2)
   - [4.3 TrueSkill](#43-trueskill)
   - [4.4 Hidden MMR vs visible rank](#44-hidden-mmr-vs-visible-rank)
   - [4.5 Matchmaking design](#45-matchmaking-design)
   - [4.6 Ranked ladder design](#46-ranked-ladder-design)
5. [Team Composition and Roles](#5-team-composition-and-roles)
6. [Netcode Implications for Design](#6-netcode-implications-for-design)
7. [Cooperation Design](#7-cooperation-design)
8. [Social Systems](#8-social-systems)
9. [Toxicity and Prosocial Design](#9-toxicity-and-prosocial-design)
10. [Griefing Prevention](#10-griefing-prevention)
11. [Cheating and Anti-Cheat Design Implications](#11-cheating-and-anti-cheat-design-implications)
12. [Community and User-Generated Content](#12-community-and-user-generated-content)
13. [Population Health](#13-population-health)
14. [Cross-Play and Cross-Progression](#14-cross-play-and-cross-progression)
15. [Checklists and Worked Examples](#15-checklists-and-worked-examples)
16. [Common Pitfalls](#16-common-pitfalls)
17. [References](#17-references)

---

## 1. How to Use This File

Load it for requests about PvP/co-op design, ranked systems, team games, lag and netcode constraints on design, social features, moderation, anti-cheat, cross-play, or UGC. Pair with `03-core-loops-and-mechanics.md` (feedback loops), `04-balance-and-economy.md` (balance), `08-player-psychology-ux-accessibility.md` (motivation, accessibility of communication), `09-monetization-and-live-ops.md` (seasons, ethics).

Evidence labels: **Established** (published research, standards, documented systems), **Industry practice**, **Heuristic** (validate in playtests). Do not invent population or toxicity statistics; when numbers are needed, take them from the developer's own telemetry.

Principle: **multiplayer is a social system first and a rules system second.** Players are each other's content. The design question is always "what do we want people to do to, with, and for each other, and how do rules, information, and rewards push them there?"

---

## 2. Multiplayer Modes

### 2.1 Mode overview

| Mode | Core tension | Strengths | Risks | Examples |
|---|---|---|---|---|
| **PvP (1v1, teams, FFA)** | Skill vs skill | Infinite replayability, esports, emergent stories | Toxicity, population dependency, skill gaps | Street Fighter, Counter-Strike, League of Legends, Rocket League |
| **PvE co-op** | Team vs system | Friendship, lower toxicity, shared goals | Content burn, carry/free-riding | Left 4 Dead, Deep Rock Galactic, Helldivers 2 |
| **Asymmetric** | Different roles with different rules | Fresh dynamics, horror/power fantasy | Balance difficulty, role queue imbalance | Dead by Daylight, Evolve, Hunt: Showdown |
| **MMO / persistent** | Social economy and progression | Community, long-term identity | Production cost, empty-world feeling | World of Warcraft, Final Fantasy XIV, EVE Online |
| **Asynchronous** | Turn-based or ghost interaction | Low commitment, time-zone friendly | Weak immediacy, cheating via ghosts | Words With Friends, Clash of Clans raids, Dark Souls messages and bloodstains |
| **Local / couch** | Shared screen, same room | Highest relatedness, easy onboarding | Screen readability, input hardware | Mario Kart, Overcooked, Super Smash Bros. |
| **Competitive-cooperative hybrid (co-opetition)** | Team inside a competition | Social drama | Betrayal toxicity | Among Us, Sea of Thieves (PvPvE), Tarkov-likes |

Key early decisions: player count per match, team structure, session length, synchronous vs asynchronous, public matchmaking vs private groups, persistence of progress, and whether the game must function with a small population.

### 2.2 PvP formats

- **1v1 duel**: purest skill measure, no blame diffusion (loss is personal) -> high stress and quick churn for losers; supply a good rating system, rematch options, practice tools.
- **Team vs team (2v2 to 5v5+)**: shared responsibility, communication, roles; blame and toxicity concentrated on perceived weakest link. Provide non-verbal comms (pings), role clarity and visible contributions beyond kills.
- **Free-for-all / battle royale**: large player count, one winner; many players lose early. Reduce dead time (quick re-queue, spectate with value, partial rewards for placement). Fortnite and Apex handle this with squads, revives and quick re-queue.
- **Objective modes**: capture, payload, king of the hill; objectives structure team movement and make skill expression broader than aim.
- **Round-based vs continuous**: round-based gives resets and economy decisions (Counter-Strike); continuous allows comeback through objectives (MOBAs).
- **Session length**: aim for natural stopping points (match end) with short queues; 5-20 minutes covers most shooter/arena formats (industry practice); MOBAs run ~20-45 minutes (League of Legends average, Dota 2 average are of that order; verify with current data before quoting).

### 2.3 PvE co-op

Co-op design is its own craft; see section 7. Basics:
- **Scale difficulty with player count** (enemy health/number/behavior) and prevent the "solo is a different game" problem.
- **Drop-in/drop-out** support, mid-session joins with catch-up, host migration or dedicated servers.
- **Loot and reward sharing** rules (personal loot vs shared) to prevent greed conflicts.
- **Roles** should matter without blocking pickup groups (see section 5).
- **Friendly fire**: adds tension and teamwork but also griefing; make it configurable.

### 2.4 Asymmetric multiplayer

- **Types**: 1 vs many (Dead by Daylight: one killer, four survivors), many vs 1 (boss hunts), role-asymmetric teams (Evolve), information-asymmetric (Spyparty, Among Us), and tool-asymmetric co-op (Keep Talking and Nobody Explodes: one player has the bomb, others have the manual).
- **Balancing**: balance the *win rate* rather than the power; each side should have a distinct fantasy and counter-strategies; give the "one" side the strongest tension (power fantasy) and the "many" side coordination. Use telemetry by role and by skill tier.
- **Queue problems**: the "one" role is often less popular or more popular than the team role; manage queue times with incentives, role bonuses, or AI fillers.
- **Onboarding**: each role has its own tutorial; learning one side informs the other (Dead by Daylight players learn killers to improve as survivors).

### 2.5 MMO and persistent worlds

- **Core pillars**: persistent identity (character, gear), social structures (guilds, parties), shared economy (auction houses, crafting), and content layers (open world, dungeons, raids, PvP).
- **Design issues**: dependence on population density (sharding/phasing/mega-servers vs. world feel), power curve and level-squish, time-gating, **economy inflation** and bots/gold sellers, and endgame loops.
- **Social glue**: guild systems, group-finding tools, and incentives for helping newcomers (mentor systems).
- **Cost**: MMO content burn is severe; plan for systemic content (crafting, housing, player-run economies like EVE) and community-driven goals.
- **Examples**: FFXIV's Duty Finder queue for dungeons lowers social friction (at the cost of fewer social bonds), WoW's raid finder similar; *Guild Wars 2* design reduces competition for kills (shared tagging, personal loot) to encourage helping strangers (industry practice).

### 2.6 Asynchronous multiplayer

- Forms: turn-based by notification, ghosts/replays (Trackmania time trials, Mario Kart ghost data), message systems (Dark Souls), base raiding (Clash of Clans), shared worlds with delayed effects (Death Stranding's structures and cargo).
- Advantages: tolerant of latency, no scheduling, low toxicity, works with small populations.
- Design points: clear notification and cadence design (avoid spam), turn timers and forfeits, anti-stalling rules, fairness when the opponent is not present (defense AI/traps), and spectating of replays.

### 2.7 Local and couch play

- **Strengths**: relatedness at its most direct; trivial onboarding by watching.
- **Design**: split-screen vs shared screen; shared-camera rules (Overcooked), accessible inputs (one-button schemes), handicap systems (Mario Kart items, Smash handicaps) to include mixed skill; short rounds and readable action at TV distance.

---

## 3. Designing for Competitive Play

### 3.1 Skill expression

**Skill expression** = the degree to which a player's skill determines the outcome and is *visible* in the result. Ingredients:
- **Multiple skill axes**: mechanical (aim, execution), tactical (positioning, timing), strategic (macro decisions, drafting), psychological (reading opponents, mind games), and social (communication, teamwork).
- **High skill ceiling, low floor**: simple rules, deep mastery (Counter-Strike, Rocket League, Street Fighter).
- **Meaningful decisions under pressure** (time limits, imperfect information).
- **Observable cause and effect**: a loss should be explainable (replays, kill cams, death recaps).
- **Skill rewards ladders**: e.g., movement tech in Apex Legends (slide-jumping) and Rocket League aerials, discovered by players and tolerated/embraced as depth. Distinguish **depth** (interesting emergent mastery) from **hidden complexity** that blocks newcomers.
- **Variance versus skill**: more randomness reduces the signal of skill; calibrate (see 3.5).
- **Feedback for improvement**: practice modes, training rooms, replays, stat breakdowns.

### 3.2 Counterplay

**Counterplay** = the opponent's ability to respond meaningfully to an action. It is the core design test for abilities, weapons, and strategies.
- **Test**: "What does the opponent do about this, and can they do it in time with the information they have?" If the answer is "nothing", it is a design bug (or a deliberate power-fantasy that needs a cost).
- **Types of counters**: avoidance (dodge, cover), disruption (interrupt, stun), outplay (bait), resource trade (spend a cooldown), information (scouting), positional (flank), and composition (pick a counter hero).
- **Telegraphs**: powerful abilities should be telegraphed in proportion to power (cast time, sound, VFX); see readability in `08`.
- **Rock-paper-scissors layers**: intransitive relationships keep metas rotating (fighting games' strike/throw/block; hero counters), but hard counters can feel unfair if there is no skill-based escape.
- **Avoid**: unavoidable one-shots from unseen sources, stun-lock chains with no break, permanent invisibility with no detection, or "no-risk" strategies.
- **Reward counterplay as well as aggression**; defensive skill needs spotlight (parry systems, defensive plays highlighted).

### 3.3 Readability

- **Competitive readability** covers: identifying friend/foe, ability state, health, cooldowns, projectile paths, hit confirmation and why you died (killcam, death recap).
- **Spectator readability** is distinct: casters and viewers need cleaner information than the players (observer UI, replays, player-cams).
- Cosmetics must not harm readability (silhouette rules, enemy highlight options); see `08` and `09`.
- **Audio readability**: footstep design, distinct ability sounds, positional audio; provide visual sound indicators for accessibility.
- **Information asymmetry** is a legitimate design lever (fog of war, hidden roles) but must be *knowable by skill* (scouting, reading), not arbitrary.

### 3.4 Snowballing and comeback mechanics

Feedback loops (see `03-core-loops-and-mechanics.md`):
- **Positive feedback** (leader gets stronger): creates decisive outcomes but makes losing teams feel hopeless early; MOBAs and RTS suffer "snowball" without safeguards.
- **Negative feedback** (leader slowed or trailing helped): keeps games close; risk: punishing skill, "rubber-banding" frustration (Mario Kart blue shell).

Tools:
| Tool | Effect | Examples / notes |
|---|---|---|
| Catch-up resources | Trailing player gets more income/experience | MOBA bounty on the leader (shutdown gold in League of Legends; bounty and streak gold in Dota 2); comeback gold/XP for trailing teams; XP bonus for lower-level heroes (note: Dota's Buyback is a respawn mechanic, a paid instant respawn, not a catch-up mechanic) |
| Loss-streak bonuses | Economy bonus after losing rounds | Counter-Strike loss bonus economy |
| Diminishing returns on leading | Cap benefit of extra kills | Score caps, soft caps |
| Objective comeback | Large swing available independent of kills | Baron/Roshan, payload overtime, last-zone mechanics |
| Late-game scaling | Trailing team has a power spike plan | Scaling heroes in MOBAs |
| Respawn and revive | Reduce permanent elimination effect | Apex Legends banners and respawn beacons |
| Handicaps | Equalize skill differences | Mario Kart items favor trailing players |
| Compression of map | Force engagements to end stalling | Battle royale shrinking zone |
| Surrender / mercy rules | End hopeless games | MOBA surrender votes; reduce frustration but also cheapen comebacks |

Design the **match arc**: opening (equal), midgame (decisions create leads), endgame (decisive but with chances). Aim for the *probability of a comeback to be nonzero throughout* but not guaranteed. Telemetry: measure win probability over time and "comeback rate" by deficit; measure early surrender and quit rates.

### 3.5 Randomness in competitive games

- **Input randomness** (before the decision: card draws, map generation) can be good for variety and decision-making; **output randomness** (after the decision: crit, miss, procs) tends to undercut skill expression (terminology popularized by Geoffrey Engelstein among others; related discussion in Elias, Garfield and Gutschera 2012; heuristic).
- Reduce high-impact variance; use **pseudo-random distribution** to avoid streaks (Dota 2 uses PRD for proc chances), bad-luck protection, and seeded fairness (same level for both players).
- Skill-testing formats (best-of-N) reduce variance at the match level.
- Random spawn and loot fairness in battle royale: accept some variance for fun; protect against feast-or-famine with loot tables, ring placement design and bounded variance.

### 3.6 Metagame and balance process

- **Metagame** = the strategies players use based on knowledge of the game and each other. Metas shift as players solve and counter strategies; designers should plan for evolution rather than static balance.
- **Balance goals**: not "all equal", but **viable diversity**: many options viable at the relevant skill tiers; no dominant strategy (see `04-balance-and-economy.md`).
- **Balancing by skill tiers**: different heroes dominate at different tiers (e.g., easy to use high win rate at low tiers, strong execution picks at high tiers); use rank-specific data.
- **Data**: win rate, pick rate, ban rate, win rate by matchup and by time, plus qualitative reports from top players. Beware selection bias (strong players choose strong heroes).
- **Patch cadence**: predictable patches (e.g., every two weeks) make metas stable enough to learn; use hotfixes for exploits.
- **Communication**: explain intent in patch notes; fighting games and MOBAs publish detailed notes.
- **Pro scene feedback** is valuable but unrepresentative; balance for different tiers separately (e.g., "pro vs casual" tuning with multipliers on ability values by mode - Overwatch and other games have varied approach).
- **Design cost of power creep**: new content must be sidegrades or reasoned buffs, or the game inflates.

### 3.7 Esports considerations

(Industry practice.)
1. **Spectator experience**: clean observer UI, replay/killcam tools, player POV, scoreboards, readable action at stream resolution, short match times with clear storylines.
2. **Match format**: best-of series, double elimination, sudden death; scheduling and time limits for broadcast.
3. **Balance stability**: tournament patches frozen before events; consistent rules; ban/pick systems (draft) add depth and viewer narrative.
4. **Tools**: custom lobbies, replays, spectator servers, API access (stats), anti-cheat, team/clan systems.
5. **Ecosystem**: publisher-run leagues vs open circuit (third-party tournament organizers); revenue shares and grassroots support; player welfare.
6. **Pro/Casual divide**: not all games need esports; planning for it constrains design toward symmetry, deterministic fairness, and heavy balance maintenance.
7. **Accessibility for viewers**: new-viewer comprehension (clear objectives, understandable stakes), audio of casters, multi-language broadcasts.
8. **Integrity**: match-fixing, cheating detection, doping-like bans (e.g., performance scripts).

---

## 4. Matchmaking and Rating Systems

**Goals of matchmaking** (in tension): (a) fair/close matches, (b) short queue times, (c) good connections (low latency), (d) social constraints (play with friends of any skill), (e) role/composition constraints, (f) variety (avoid same opponents), and (g) protecting new players. You cannot maximize all at once; define priorities explicitly.

### 4.1 Elo

- **Model (established)**: Arpad Elo's system (adopted by FIDE in 1970; Elo 1978 *The Rating of Chessplayers, Past and Present*) models each player's skill as a rating R. The expected score of A vs B is
  `E_A = 1 / (1 + 10^((R_B - R_A) / 400))`.
  After a game with actual score S_A (1 win, 0.5 draw, 0 loss), the update is
  `R_A' = R_A + K * (S_A - E_A)`.
  K controls update size (e.g., higher for new/low-rated players, lower for established; common choices vary, treat as tunable).
- **Properties**: zero-sum between two players; ratings are relative; a 400-point difference means the stronger player is expected to score ~91% (E = 1/(1+10^-1) ~ 0.909).
- **Limits**: assumes fixed variance (no uncertainty measure), designed for 1v1, slow to converge for new players, inactive players hold stale ratings, and team games require extension (team average or individual contribution).
- **Use**: simple, transparent; good baseline for 1v1 and small communities.

### 4.2 Glicko and Glicko-2

- **Glicko (Mark Glickman, 1995/1999)** adds **ratings deviation (RD)**, a measure of uncertainty. RD rises with inactivity and falls with games; the rating update magnitude depends on RD (uncertain players move more) and on opponents' RD. Output is a rating plus an interval (e.g., rating +/- 2 RD gives a ~95% interval).
- **Glicko-2** adds **volatility (sigma)** measuring how erratic a player's performance is, and works in rating periods. Defined in Glickman's paper "Example of the Glicko-2 system"; uses an iterative algorithm to update volatility. Used in many chess sites (e.g., lichess) and various games.
- **Why it matters for games**: matchmaking can use RD to treat new players differently; displayed ranks can use conservative estimates (rating - k*RD).
- Papers: http://www.glicko.net/glicko/glicko2.pdf and http://www.glicko.net/glicko/glicko.pdf (Glicko, 1999).

### 4.3 TrueSkill

- **TrueSkill (Herbrich, Minka and Graepel, 2006, NIPS)**: Bayesian skill rating developed at Microsoft Research for Xbox Live. Each player has a Gaussian skill belief N(mu, sigma^2); matches of any team structure and player count (teams, FFA, partial play) update beliefs via **factor graphs and message passing (expectation propagation)**. Supports draws and team games and estimates **match quality** (probability of draw) for matchmaking.
- **Displayed rank** often uses a conservative estimate, e.g., `mu - 3*sigma`, so that new players start low and rise as certainty grows (a convention used in Halo-era systems; check specifics).
- **TrueSkill 2 (Minka et al., 2018)** extended the model with in-game performance (e.g., kills), experience, squad effects and quitting; Microsoft Research technical report.
- Paper: https://papers.nips.cc/paper/2006/hash/f44ee263952e65b3610b8ba51229d1f9-Abstract.html
- **Limits**: patents and licensing history (TrueSkill is Microsoft-patented; open implementations exist, check licensing), assumption of additive team skill, and difficulty modeling roles and synergies.

### 4.4 Hidden MMR vs visible rank

- **Hidden MMR** (matchmaking rating): the true internal estimator used to match players. **Visible rank**: tiers/divisions/leagues displayed to players for goals and status.
- Reasons to separate: matchmaking needs accuracy and responsiveness, while rank display needs stability, motivation, and psychological safety (ranks that go up and down every game demoralize).
- Common visible-rank features: placement matches (initial calibration), divisions with promotion/demotion series, rank decay for inactivity (use sparingly), seasonal soft resets, and "protection" from demotion after promotion.
- **Transparency vs gaming**: publishing exact formulas invites exploitation; providing too little breeds distrust and conspiracy theories. Middle path: explain principles (win/lose, margin of victory or performance weighting?), show progress within tier, and give rank history.
- **Performance-based adjustments** (individual stats affecting rating) motivate stat padding and discourage teamwork; use with caution (many games stay win/loss-based for this reason).
- **Smurfs and boosters**: new accounts at high skill; use rapid-calibration (high K or sigma) so that smurfs leave low ranks quickly, plus phone/ID verification and detection.

### 4.5 Matchmaking design

Parameters and trade-offs:
| Parameter | Tighter | Looser |
|---|---|---|
| Skill window | Fairer matches | Faster queue |
| Ping limit | Better play | Smaller pool / longer queues |
| Party-size mixing | Fair vs solo | Faster; but groups outperform solos via communication |
| Role constraints | Better compositions | Longer queues |
| Search expansion | - | Window widens over time (a standard approach) |

Practices:
1. **Expanding search window**: start tight; widen over time; cap the expansion to avoid stomps.
2. **Party matching**: groups of friends get coordination advantage; either match parties vs parties or adjust effective rating for party size.
3. **New-player protection**: bots, easy lobbies, or separated pools early (Fortnite/Call of Duty used bot lobbies in some modes - verify per game), but be careful about deceiving players (some games hide bots; consider transparency).
4. **Bots as filler** to reduce queue times in low populations.
5. **Latency-based region selection** and cross-region queue options.
6. **Rematch / leave penalty** to reduce match-level abandonment: penalties and rewards for staying.
7. **Backfill**: replace leavers when possible, or provide reduced loss penalties for the remaining team.
8. **Match quality metrics**: predicted win probability, observed fairness (distribution of outcomes), queue time distribution, abandonment rate, and satisfaction surveys.
9. **Engagement-optimized matchmaking** (EOMM, research by Chen et al. 2017, Electronic Arts) proposes matching to maximize retention; patents on similar ideas (e.g., Activision) raised ethical controversy; treat as an ethical risk if matchmaking is manipulated to induce spending (see `09`).
10. **Skill-based vs connection-based matchmaking (SBMM/CBMM)** is a perennial community debate in shooters; the trade-off is between fairness to the lower-skilled players and the stress ("sweaty lobbies") felt by high-skilled ones; offering both ranked (strict) and casual (looser) queues is the common response.

### 4.6 Ranked ladder design

- **Seasons**: soft resets compress ranks, rewards at end, new season content (see `09`).
- **Tier distribution**: shape tiers so that most players land in the middle with some tail; avoid ranks that stigmatize (a "Bronze" label can shame players; some games rename/rework).
- **Placement**: 5-10 games typical (heuristic) with high-variance updates.
- **Promotion systems**: series vs points; inflate/deflate issues; guard against rating inflation or deflation by calibrating zero-sum or net-positive adjustments.
- **Team ranked**: queue as duo/trio/five; separate leaderboards for solo and group.
- **Leaderboards**: top-N visible; region filters; anti-cheat verification; avoid showing only top players (also show friends/relative standing).

---

## 5. Team Composition and Roles

- **Roles** give players identity and responsibilities; the classic MMO trinity is tank / healer / damage dealer. Hero shooters (Overwatch: tank/damage/support; Overwatch 2 moved to 5v5 with one tank) and MOBAs (carry, support, mid, jungle, top) use role structures.
- **Why roles help**: they reduce redundancy, create interdependence, and give shy players clear contributions. **Risks**: queue imbalance (shortage of tanks/healers), role lock frustration, and toxic blame by role.
- **Role queue vs open queue**: role queue (Overwatch's 2-2-2 role queue in 2019) fixes composition problems and queue-time spikes at the cost of flexibility and counter-picking; open queues enable creativity but let teams stack the same role. Evidence is mostly industry practice and community reaction.
- **Composition design**: ensure there are *multiple viable compositions* and the draft/lobby phase surfaces counter-picks (draft modes: Dota's Captains Mode, League's ban/pick).
- **Synergy and counters**: give heroes reasons to pair (combos) but avoid hard dependencies that make solo queue miserable.
- **Role complexity tiers**: provide easier "entry" roles and clear difficulty ratings, while giving advanced roles depth (Overwatch hero difficulty ratings, League champion complexity).
- **Visible contribution**: not all value shows in kills; show assists, healing, objective time, damage mitigation, and use "play of the game" or end-of-match commendations to highlight support and tank play.
- **Communication tools**: pings, quick chat, drafting lobby; see section 8.
- **Fallback behavior**: when a role is empty, game must still be playable (e.g., Apex has no hard roles but soft synergy; Deep Rock Galactic classes can all be played with 1-4 players).
- **Onboarding**: teach roles in tutorials and training (scoped to responsibilities, not just abilities).

---

## 6. Netcode Implications for Design

Network latency is a **design constraint**, not just an engineering concern. Know the models and build rules, abilities and feedback that respect them.

### 6.1 Latency basics

- **Latency (ping)** = round-trip time between client and server; **jitter** = variation; **packet loss** = dropped packets; **tick rate** = server simulation updates per second (e.g., 20, 30, 60, 128; varies by game and server cost).
- **Perceptual thresholds** (heuristics): under ~50 ms feels near-instant for most; 100 ms is noticeable in twitch games; above ~150-200 ms play degrades for action games; fighting games are especially sensitive (frame-perfect inputs).
- **The speed of light** and routing define a floor: intercontinental play adds 100+ ms. Region-based servers and matchmaking are required for real-time games.

### 6.2 Architectures

| Model | Description | Pros | Cons | Good fit |
|---|---|---|---|---|
| **Authoritative server + client prediction** | Server owns truth; clients predict own movement and reconcile | Cheat-resistant, responsive | Server cost, rubber-banding when mispredicted | FPS, action, battle royale |
| **Peer-to-peer lockstep** (deterministic) | Peers exchange inputs; sim must be deterministic | Low bandwidth, many units (RTS) | Input delay equals slowest peer; desync; cheating (maphacks) | RTS (Age of Empires, StarCraft), turn-based |
| **Delay-based netcode** | Add input delay equal to latency so all peers stay in sync | Simple | Feels laggy as ping rises | Casual/older fighters |
| **Rollback netcode (GGPO)** | Run immediately with predicted opponent input; roll back and re-simulate when real input arrives | Local-feel input at moderate ping | Requires deterministic fast re-simulation; visual rollback artifacts; CPU cost | Fighting games (Skullgirls, Street Fighter 6, Guilty Gear Strive) |
| **Snapshot interpolation** | Server sends world snapshots; clients render slightly in the past | Smooth remote entities | Remote players displayed in the past | Most FPS and action games |
| **Client-authoritative** | Client decides outcomes | Zero perceived latency | Easy cheating | Co-op PvE, low-stakes |

- **Rollback vs delay**: GGPO (Tony Cannon, 2009) popularized rollback in fighting games: the game speculatively executes with predicted input and re-simulates after corrections, hiding latency up to a limit (frames of rollback budget). Delay-based adds fixed input frames of delay and stalls on packet loss. Design implication: game logic must run deterministically and *fast enough to re-simulate multiple frames in one frame*; animation/VFX/audio must tolerate being rewound (e.g., defer triggering audio of uncertain events).
- Sites: https://www.ggpo.net/ ; Wikipedia overview: https://en.wikipedia.org/wiki/Rollback_netcode .

### 6.3 Client-side prediction, interpolation, reconciliation, lag compensation

- **Client-side prediction**: the client applies its own inputs immediately (movement), then **reconciles** with authoritative server state, replaying unacknowledged inputs. Reference: Gabriel Gambetta's *Fast-Paced Multiplayer* series, e.g., https://www.gabrielgambetta.com/client-side-prediction-server-reconciliation.html
- **Entity interpolation**: remote entities are rendered between received snapshots (~100 ms in the past), https://www.gabrielgambetta.com/entity-interpolation.html
- **Lag compensation**: the server rewinds other players' positions to the time the shooter fired (based on shooter latency and interpolation) to validate hits; Valve's Source engine documentation: https://developer.valvesoftware.com/wiki/Source_Multiplayer_Networking and Bernier's "Latency Compensating Methods in Client/Server In-game Protocol Design and Optimization" (2001): https://developer.valvesoftware.com/wiki/Latency_Compensating_Methods_in_Client/Server_In-game_Protocol_Design_and_Optimization ; Gambetta: https://www.gabrielgambetta.com/lag-compensation.html
- **Side effect ("shot behind cover")**: lag compensation favors the shooter; the target can die after reaching cover from their perspective. Design around it: avoid ultra-short-lived defensive abilities that cannot be reconciled, or accept and communicate.
- **Networked physics/state sync**: Glenn Fiedler's articles: https://gafferongames.com/post/introduction_to_networked_physics/ and https://gafferongames.com/post/state_synchronization/ ; deterministic lockstep: https://gafferongames.com/post/deterministic_lockstep/ ; overview: https://gafferongames.com/post/what_every_programmer_needs_to_know_about_game_networking/

### 6.4 Designing around latency

1. **Pick the model first** based on genre: shooters = authoritative + prediction + lag compensation; fighting = rollback; RTS = lockstep; co-op PvE = can be more client-trusted.
2. **Make abilities latency-tolerant**: longer cast times and wind-ups, area effects with generous hitboxes, and targeted abilities that resolve on the server tolerate ping better than precision-dependent hitscan. Dodge windows must be longer than typical ping + jitter.
3. **Avoid sub-100 ms reaction demands** in online-only abilities for global audiences; if the game demands frame-perfect timing (parries), restrict matchmaking by ping or use rollback.
4. **Hide latency with animation**: wind-ups, anticipation animations, and immediate local feedback (muzzle flash) while hit confirmation arrives later (hit markers on server confirmation).
5. **Authority per mechanic**: movement predicted, damage authoritative; projectiles spawn client-side with server reconciliation; physics objects may be server-owned.
6. **Mispredictions must be graceful**: smooth corrections (blend rather than snap); avoid mechanics where tiny disagreement is catastrophic (e.g., one-pixel platforming in online co-op).
7. **Interaction ordering**: define how simultaneous actions resolve (two players grab the same item; who gets it?) and show deterministic rules (server arrival order vs priority).
8. **Packet loss/jitter**: show network quality indicators; offer low-bandwidth modes; graceful degradation.
9. **Server cost**: tick rate and player count drive costs; in F2P, tick rate decisions are budget decisions.
10. **Host migration and disconnects**: P2P games need host migration; design for AI takeover or pause on disconnect (reconnect window).
11. **Region and cross-play**: keep latency visible; allow region lock; consider ping-aware matchmaking.
12. **Testing**: use network simulators (clumsy, tc/netem, platform tools) to test at 50/100/200 ms, 1-5% loss, and jitter; test with bots to emulate worst-case players.
13. **Async fallback**: for very high-latency conditions consider asynchronous modes.

---

## 7. Cooperation Design

Cooperation arises when the design makes teammates need each other and rewards helping.

### 7.1 Interdependence

- **Positive interdependence** (Deutsch 1949; Johnson and Johnson): team members succeed only if all succeed. Mechanisms: **shared goals**, **shared fate** (team fails if one dies), **complementary roles**, **shared resources**, **sequential dependency** (one opens doors for another), and **information splitting** (each sees different data).
- **Goldilocks interdependence**: too little = parallel solo play; too much = one player's mistakes/absence ruin the experience (and invite blame). Offer *recoverability* (revives, lifelines) to soften.
- **Individual accountability**: players need visible contributions so no one feels like a passenger or like a carried burden.

### 7.2 Complementary roles and shared/separate resources

| Design lever | Effect | Example |
|---|---|---|
| **Complementary abilities** | Teamwork required to solve problems | *It Takes Two*: each level gives the two players different, complementary tools (nail and hammer, time-manipulation clock halves); mandatory co-op with no solo mode |
| **Role classes with clear jobs** | Identity and mutual need | *Deep Rock Galactic*: Driller (terrain), Engineer (platforms, turrets), Scout (light, mobility), Gunner (zipline, shields); each class has unique tools that solve mission problems; all players share a mission goal; the "Rock and Stone" culture encourages helping |
| **Shared resources** | Negotiation, strategy | Team ammo/supply pool; shared base; shared lives |
| **Separate resources** | Autonomy, less conflict | Personal loot and inventory; individual cooldowns |
| **Mutual rescue** | Salvation creates bonding | *Left 4 Dead*: incapacitated survivors must be rescued by others; special infected (Smoker, Hunter, Boomer, Charger, Jockey, Spitter) isolate players, forcing the team to react |
| **Dynamic difficulty by team state** | Keep tension | *Left 4 Dead's* AI Director adjusts pacing to team stress ("emotional intensity") and spawns events; Mike Booth's GDC/Valve presentation: https://steamcdn-a.akamaihd.net/apps/valve/2009/ai_systems_of_l4d_mike_booth.pdf |
| **Friendly fire** | Care and risk | Helldivers 2: friendly fire and stratagem mistakes create chaotic stories; needs forgiving tuning |
| **Information asymmetry** | Communication | *Keep Talking and Nobody Explodes*, *Overcooked* (kitchen coordination) |

### 7.3 Cooperation patterns

1. **Pull-to-push**: pull the team apart (threats isolate players) then push them together (rewards for regrouping). L4D's special infected do this.
2. **Combo / synergy windows**: skills that combine (apply status, then exploit it) with a visible cue, e.g., MOBA team fights, Destiny elemental combos.
3. **Sacrifice and heroics**: mechanics where one player can take a risk to save others, with the saved player's gratitude (thanks emote, endorsements).
4. **Division of labor with a shared payoff**: split to complete objectives, rejoin for a finale.
5. **Spatial coordination**: formations, line-of-sight management, covering fire.
6. **Temporal coordination**: simultaneous actions (two switches), countdowns; ping tools to coordinate.
7. **Communication scaffolds**: ping systems and quick chat for those without voice; shared map markers.
8. **Pickup-group resilience**: cooperation must work with strangers who do not talk: legible roles, auto-assists (revive prompts), and AI backfill.
9. **Anti-carry**: avoid one player doing all the work. Scale rewards by contribution, not just outcome; include goals that require each role.
10. **Difficulty scaling for number of players** and the presence of voice.
11. **Reward helping**: score for assists/revives/heals; end-of-mission stats that spotlight support roles.

### 7.4 Co-op pitfalls

- **Alpha player / quarterbacking**: one player dictates actions; mitigate with distinct information per player and individual objectives.
- **Free-riding / AFK**: AI takeover, vote-kick, reduced rewards for inactivity, but not punishing legitimate disconnects.
- **Leaver penalty fairness**: penalize repeated abandonment, not single disconnects.
- **Over-reliance on a role**: if no one picks the healer, the run fails; ensure that fallbacks exist (consumables, AI).
- **Loot disputes**: use need-before-greed, personal loot, or trade locks.

---

## 8. Social Systems

### 8.1 Friends, parties, presence

- **Friend list and presence**: show online/in-game/joinable status; one-click join; platform integration (Steam, Xbox, PlayStation, Discord) and cross-platform friends via in-game IDs.
- **Parties/lobbies**: ready-check, shared queue, role/loadout selection, text/voice. Allow **party leader hand-off** and visible party composition to opponents (fairness).
- **Invite flow friction** is a major driver of friend play: invite friends in 2 clicks or less (heuristic target).
- **Playing with friends of different skill**: matchmaking by average/high/blend of party rating; unranked or casual alternatives.
- **Recently played with**: allows adding good teammates; reduces friction for forming relationships (and for reporting).
- **Block/mute/hide** tools must be visible and effective (muting persists; blocked player cannot spectate or message).

### 8.2 Guilds / clans / teams

- **Functions**: belonging, shared goals, social obligation (retention driver), economic cooperation (storage, crafting), and organized content (raids, wars).
- **Design needs**: onboarding for guild-less players (guild finder, recruitment tools), guild progression that doesn't punish small guilds, tools for leaders (roles, permissions, calendars, message of the day), anti-abuse tools, and activity requirements without guilt.
- **Risks**: elitism, drama, leader burnout, kicking and exclusion; mitigate with transparent governance tools, multiple small-group formats (friends-of-friends), and light-touch communities ("casual guilds", "communities").
- **Rewards**: shared goals with scaling targets based on active members to avoid penalizing small groups.

### 8.3 Chat

- **Text chat**: channels (team/all/party/guild), filters (profanity, slurs; user-configurable severity), rate limits, report from chat, mute by default for all/opposing chat (several games default all-chat to off to reduce toxicity; Riot Games has publicly discussed testing this in League of Legends - look up the original Riot posts for the dates and results before quoting).
- **Voice chat**: push-to-talk vs open mic; proximity voice (Among Us mods, Sea of Thieves, DayZ), party vs team; voice moderation (ML-based transcription flagging as tried by Activision with ToxMod for Call of Duty - verify current status), and consent/privacy.
- **Accessibility (CVAA and beyond)**: speech-to-text and text-to-speech for chat (see `08`), non-verbal communication alternatives.
- **Language barrier**: auto-translation of chat, wheel chat, ping systems reduce barriers.
- **Safety by age**: restricted chat for minors by default (FTC v. Epic COPPA aspects; see `09`).

### 8.4 Ping and quick-comms systems

- **Apex Legends contextual ping** (Respawn, 2019) is a landmark: a single button marks locations, enemies, loot, and elicits context-sensitive spoken lines (the character says "enemy here", "I need ammo"); loot pings can request items and teammates can accept/decline with an item drop. It allows effective tactical communication **without voice**, supports many languages and reduces toxicity opportunities. Commentators frequently cite it as the best-in-class example (see Wikipedia overview for Apex: https://en.wikipedia.org/wiki/Apex_Legends and developer interviews).
- **Design principles for ping systems**: *context-sensitivity* (the same input means different things depending on target), *low friction* (one button, fast, not needing menu), *clear persistent markers* with ownership and expiry, *distinct audio-visual cues* that don't spam, and *rate limiting* to prevent spam abuse; plus *accessibility* (color-independent markers, text labels).
- Other examples: *League of Legends* ping wheel (Danger, On my way, Assist me, Missing enemy), *Dota 2* chat wheel, *Overwatch* comms wheel, *Rainbow Six Siege* markers, *Left 4 Dead* auto-callouts ("Hunter!" voice lines).

### 8.5 Emotes and social expression

- **Emotes** give players non-verbal self-expression and social rewards (in-game gestures, dances, sprays). Considerations: moderation of offensive imagery, ability to disable others' emotes (accessibility and sensory), gameplay-neutral hitboxes (no exploiting emote animations for hitbox advantage), and tone alignment.
- **Positive social rituals**: bow before matches (e.g., Dark Souls "Gesture", Rocket League "What a Save!" quick chat, Journey's non-verbal chime) build prosocial culture.
- *Journey* shows how removing text/voice (only a note) leads to cooperative behavior between strangers; the anonymous companion mechanic is a case study in prosocial constraint design.

### 8.6 Trading and economy social systems

- **Direct trading** enables player economies and community, but invites scams, real-money trading (RMT), duplication exploits, and inflation (Diablo 3's real-money auction house was an infamous case that was closed in 2014; widely documented). Mitigate with trade restrictions (soulbound items, trade limits, trade holds), audit logs, and market taxes/sinks.
- **Auction houses and player markets**: sink fees, price history, anti-manipulation measures; see `04-balance-and-economy.md`.
- **Gifting**: allows friends to give; abuse as laundering path for stolen/cheated currency; cap/age limits.

### 8.7 Social features checklist

- [ ] Add friends in one action (including recent teammates).
- [ ] Join friends in two clicks.
- [ ] Mute/block/report visible, instant, persistent.
- [ ] Non-voice comms (ping/quick chat) available.
- [ ] Safe defaults for minors.
- [ ] Parties of mixed skill handled.
- [ ] Newcomer-friendly social paths (guild finder, mentors).
- [ ] Positive reinforcement surfaces (endorsements, commendations).

---

## 9. Toxicity and Prosocial Design

### 9.1 What the research and industry practice say

- **Toxicity is a design outcome as well as a behavior problem.** Competition, anonymity, low cost of abuse, blame attribution to teammates, and public failure raise risk. Designs that reduce anonymity cost, blame attribution, and zero-sum frustration lower it.
- **Most toxicity comes from ordinary players on bad days**, not only from a small group of chronic offenders. Riot Games' player behavior research (Jeffrey Lin, 2013-2015, Lead Designer of Social Systems) analyzed League of Legends chat data and reported that the majority of toxic messages came from players who were generally not toxic and that a small fraction of players accounted for a minority of the toxicity (see Lin's GDC talks and Riot's blog posts; verify exact figures at the source before quoting). Takeaways: both punishment and positive reinforcement are needed; chronic offenders need removal, while average players respond to nudges.
- **The Tribunal (League of Legends, 2011-2014)**: community review of reported cases; later replaced by automated "Instant Feedback" systems that show offenders the offending chat lines and penalties with a short delay, which Riot reported reduced repeat offenses (reported by Riot; verify details).
- **Priming/nudges**: Riot tested loading-screen tips and "tips" with colored text and reported that positive framing ("players who cooperate are more likely to win") reduced negative behavior in A/B tests (reported by Lin; treat as industry-reported findings).
- **Overwatch Endorsement system (2018)**: after each match, players can endorse teammates and opponents in categories **Shot Caller, Teammate, Sportsmanship**; endorsement levels (1-5) show on the player profile and unlock cosmetic rewards, and Blizzard reported a decrease in toxic chat after launch (Jeff Kaplan and Blizzard developer updates; verify the exact percentage at the source if quoting). Features: the endorsement is only possible for teammates/opponents within the match; positive reinforcement from peers rather than reports.
- **Clean-up tooling**: reporting systems that work (clear categories, quick response, feedback to reporters "action was taken"), automatic detection of slurs, voice analysis, and restricting chat.
- **Social science**: contact hypothesis (cooperation reduces prejudice) suggests co-op friendly design; the "online disinhibition effect" (Suler 2004) describes reduced inhibition when anonymous, asynchronous, invisible.
- **Industry coalition**: the Fair Play Alliance (2017-, publishers share practices); its "Disruption and Harms in Online Gaming Framework" and "Fair Play Alliance Positive Play Charter" document practice. (Look up the latest resources at fairplayalliance.org before citing specifics.)
- **Prevalence reports**: ADL's annual "Hate Is No Game" reports on harassment in online games: https://www.adl.org/resources/report/hate-no-game-hate-and-harassment-online-games-2023 (use current edition).

### 9.2 Prosocial design toolkit

| Intervention | Mechanism | Notes |
|---|---|---|
| **Opt-in all-chat / default off** | Reduce exposure to opponents' abuse | Lowers toxicity; reduces taunting fun; consider "opt-in" or "ping only" |
| **Positive reinforcement** (endorsements, commendations, honor) | Reward good behavior | Overwatch endorsements; League Honor; keep rewards cosmetic and modest to avoid gaming |
| **Reporting with feedback** | Trust the system | Tell reporters when action was taken |
| **Instant feedback and graduated penalties** | Education then punishment | Text warnings, chat restrictions, queue delays, suspensions, bans |
| **Reduce blame surfaces** | Fewer fights | Show team contribution beyond kills; fewer scoreboard comparisons; no public "worst player" shaming |
| **Reduce zero-sum frustration** | Fewer rage triggers | Short matches, quick requeue, surrender options, comeback mechanics |
| **Mute and block tools** | Individual control | Easy, persistent; reduce reliance on enforcement |
| **Nudges and priming** | Behavioral prompts | "Are you sure you want to send this?" prompts before sending messages flagged as toxic (tested by some platforms) |
| **Matchmaking for behavior** | Separate toxic from non-toxic | Low-priority queues for penalized players, "honor" based matchmaking |
| **Role/draft pressure relief** | Less conflict | Role queue, fair pick order |
| **Friendly onboarding** | Retain new players | Protect novices in early matches (avoid veterans' stomp) |
| **Cooperative constraints** | Prosocial play | Limited communication (Journey) or mandatory co-op (It Takes Two) |
| **Moderator well-being** | Sustainable operation | Rotation, tooling, mental health support |

### 9.3 Principles

1. **Define harm and norms publicly** (code of conduct) and enforce consistently.
2. **Layered approach**: design (prevent), tools (empower), detection (automated), enforcement (human review), and education (feedback).
3. **Measure**: report volume, repeat offender rate, time to action, chat toxicity classifier metrics, player retention among targets of abuse (marginalized players quit faster), and surveys.
4. **Protect the targets**: women, LGBTQ+, and minority players face disproportionate harassment (ADL and other reports); provide filters and safe-mode queues without isolating them.
5. **Avoid false positives**: banter between friends is not toxicity; allow friends-only unfiltered chat; appeal processes.
6. **Don't rely on punishment alone**: players need positive paths back (rehabilitation, graduated).
7. **Transparency**: publish enforcement summaries (transparency reports).

---

## 10. Griefing Prevention

**Griefing** = deliberate behavior to ruin others' experience without playing to win (team-killing, throwing/feeding, blocking doors, stealing kills/loot, AFK, spawn camping, trolling objectives).

Prevention by design:
1. **Remove the capability**: limit friendly fire, disable collision between teammates in chokepoints, prevent building in critical paths, allow blocked objects to be removed after a timer.
2. **Remove the incentive**: griefing for loot or rank gain (win trading, boosting) should be unprofitable; no rewards for kills on teammates; matchmaking penalties.
3. **Add friction/cost**: team-kill penalties scaled with repeated offenses; "karma" systems (Counter-Strike and Rainbow Six use team damage penalties; automatic kick after threshold).
4. **Add recourse**: vote kick, reconnect, report with replay evidence; allow victims to disengage without a penalty (e.g., leave without loss when griefed).
5. **Detect patterns**: statistical detection of intentional feeding (deaths vs enemy proximity), AFK detection, and cooperation signals.
6. **Protect social spaces**: spawn protection/invulnerability, safe zones, spectator-only for banned players.
7. **Sanctions**: temporary restrictions, ranked bans, hardware/ID bans for chronic abusers; lessened penalties first.
8. **Avoid punishing innocents**: lag, disconnects, and accidental team damage must be identified; threshold logic with context.
9. **Free-to-play ban evasion**: link bans to phone number, hardware ID, or paid-account verification.
10. **Grief-resistant design examples**: *Sea of Thieves* sinking and respawn fairness; *Dead by Daylight* kill-switch tools like bleed-out and anti-camping mechanics (hooks have timers and anti-camp bars for survivors) — game-specific designs that limit time-wasting.

---

## 11. Cheating and Anti-Cheat Design Implications

(Anti-cheat as a design constraint; for security specifics consult security engineers.)

- **Core principle**: *never trust the client.* The server decides outcomes that matter; clients display and predict. Any state or logic on the client (positions of all players, hidden info) can be read or modified.
- **Cheat categories**: aimbots/triggerbots, wallhacks/ESP (reading hidden info), speed hacks, duping exploits, macros/scripts, boosting/win-trading, account trading/RMT, DDoS/lag switching, and exploiting bugs.
- **Design implications**:
  1. **Minimize the information sent to clients** (server-side occlusion culling: only send positions of enemies who could be visible) to blunt wallhacks.
  2. **Server authority over economy and progress** (loot, XP, currency) to prevent duplication.
  3. **Validate inputs**: rate limits, movement plausibility checks, and rewind-based hit validation.
  4. **Statistical detection**: unusual accuracy, reaction times, headshot rates, impossible movement; machine-learning detection; manual review with replays.
  5. **Client-side anti-cheat** (kernel-level drivers like Vanguard, EasyAntiCheat, BattlEye): effective at detecting known tools but raises privacy/security and platform-compatibility concerns (e.g., Linux/Steam Deck support is affected); design the policy thoughtfully.
  6. **Report-driven review**: reports prioritized by reliability; **overwatch-like** systems (CS:GO Overwatch, community review).
  7. **Hardware and account-level bans**; phone verification; ranked-entry requirements to raise the cost of smurfing/cheating.
  8. **Trust factor / trust matchmaking**: matching suspected cheaters or low-trust accounts together (Valve's Trust Factor in CS:GO/CS2).
  9. **Design away cheating motives**: rewards that depend on solo grind create botting incentives; leaderboards need verified runs (replay validation).
  10. **Transparency**: publish ban waves and stats, so players believe cheating is addressed.
  11. **Offline/single-player cheating** is not necessarily a problem; separate from leaderboards (cheat-flagged saves).
  12. **P2P risks**: IP exposure/DDoS, desync exploits; prefer relay servers.
  13. **Esports integrity**: in-person events with controlled hardware, admin tools, and anti-collusion rules.
- **Social cost of false positives**: wrongful bans destroy trust and cause refunds and PR damage; provide appeals.

---

## 12. Community and User-Generated Content

### 12.1 UGC types and value

- **Maps/levels** (Super Mario Maker, Halo Forge, Fortnite Creative/UEFN, Dreams), **mods** (Skyrim, Minecraft, Counter-Strike origins), **cosmetics and items** (Steam Workshop, Team Fortress 2 community items with revenue share), **custom game modes** (Dota 2 custom games, Warcraft III's Defense of the Ancients mods, Roblox experiences), **replays and streams**, and **community wikis/guides**.
- **Why UGC**: extends content life, builds identity and ownership (autonomy, competence for creators), and creates marketing through creators. It can also be a platform-business model (Roblox, Fortnite creator economy).

### 12.2 Design for UGC

1. **Tools first**: UGC quality depends on the creator tools' usability and power; invest in templates, tutorials, and sandboxed scripting.
2. **Validation**: Super Mario Maker requires creators to clear their own level before upload, eliminating impossible levels; copy the principle: *proof of playability*.
3. **Discovery and curation**: search, tags, ratings, featured lists, "my favorites", editor's picks; avoid popularity-only sorting that buries new creators; provide time-limited visibility boosts.
4. **Incentives**: credit, leaderboards, revenue share, contests, creator programs; protect against copycat/plagiarism.
5. **Moderation**: automated and human review of UGC for IP infringement, hateful content, malware, and child safety; legal compliance (DMCA/notice-and-takedown, EU Digital Services Act obligations); clear content policy.
6. **Technical safety**: sandbox mods, limit access to file systems, review scripts, and avoid executing arbitrary code on consoles without checks.
7. **Quality vs quantity**: curated "official" levels as a baseline; UGC as supplement.
8. **Compatibility**: patches can break UGC; give versioning and tooling.
9. **Creator wellbeing and fairness**: transparent revenue shares, ownership terms and licensing.
10. **Community norms**: positive reinforcement of creators, feedback loops, and showcases.

### 12.3 Community health practices

- Cultivate a **core of ambassadors**; support creators and streamers (tools, early access).
- Offer **in-game spectating and replay sharing** to enable content.
- Provide **community goals and shared milestones** (collective rewards).
- Build **third-party ecosystems** with APIs (stats, overlays); manage rate limits and ToS.
- Use **moderation scaled to community size**; invest in tooling.

---

## 13. Population Health

Multiplayer games die from emptiness. Population health is a design problem as well as a marketing one.

### 13.1 Concepts

- **Critical mass**: the minimum concurrent players needed for acceptable queue times and match quality in each mode, region, and skill tier. Fragmentation by mode, platform, region, and skill reduces it.
- **Funnel**: acquisition -> onboarding -> retention -> social integration -> mid/late game; the pool is replenished by new players and shrinks by churn.
- **New player experience**: veterans' dominance and complex systems cause new-player churn (the "new player cliff"); essential in competitive games where unskilled newcomers face veterans.
- **Skill distribution**: if only experts remain, the bottom disappears and the game stagnates; keep the average player's experience positive.
- **Queue time as a KPI**: monitor median and 95th percentile queue times by mode/region/rank.

### 13.2 Design levers

1. **Limit mode fragmentation**: fewer, well-populated playlists; rotate modes rather than permanent options (Call of Duty and Halo playlists rotate modes to concentrate populations; historical multi-map pack splits harmed populations).
2. **Free-to-play** and cross-play widen the pool.
3. **Bots** as filler, as training, and for off-peak hours; make them credible and ideally labeled.
4. **Playlist and event scheduling** to concentrate players at key times.
5. **Smurf and boost management**: preserve novices' experience.
6. **Mentoring and newbie modes**: separate queues for first N matches; "protected" ranked entry.
7. **Skill-based pairing with clear fairness** for novices.
8. **Social anchors**: guilds, friend invites, and cross-promotion.
9. **Regional server strategies**: ensure low latency for major regions; combine low-population regions as needed.
10. **Fresh-start mechanisms**: seasons, leagues, wipes (Path of Exile leagues, Diablo seasons) re-concentrate populations.
11. **Content refresh** to bring back lapsed players (see `09`).
12. **Sunsetting plans**: when populations dwindle, merge servers or modes; allow private servers and offline modes at end-of-life.
13. **Design for small-population viability**: co-op modes, asynchronous play and bot modes keep a game alive after the peak.

### 13.3 Metrics

CCU peaks and troughs by time zone, queue time distribution, match quality distribution (predicted vs actual), new-player D1/D7 retention, share of matches with bots/backfill, rank distribution shape, and social graph stats (average friends per player).

---

## 14. Cross-Play and Cross-Progression

- **Benefits**: larger pools, play with friends across platforms, longer life, and lower matchmaking times.
- **Challenges**:
  1. **Input parity**: mouse+keyboard vs controller fairness (aim assist strength, input-based matchmaking, optional input-based queues; Fortnite/Call of Duty/Apex discussions).
  2. **Platform policies and certification**: each platform has requirements for friends, chat, and purchases; account linking.
  3. **Performance disparities**: frame rate and latency differences (mobile vs high-end PC).
  4. **Anti-cheat on PC vs consoles**: cheaters in cross-play pools; allow opt-out; platform-specific ban propagation.
  5. **Social features**: unified friends lists, cross-platform chat (voice/text), name systems, and parental controls.
  6. **Economy and entitlements**: cross-progression (same account across platforms), store purchase portability and platform fees.
  7. **Content parity and patch sync**: simultaneous patches across platforms, certification delays.
  8. **Fairness UI**: show platform icons, allow cross-play toggles, and communicate what is on.
- **Design strategy**: default cross-play on with opt-out; input-based matchmaking for competitive; unified account system early (retrofits are expensive); test latency across platforms.
- **Examples**: Rocket League (early adopter of cross-platform play), Fortnite (cross-platform with unified accounts), Call of Duty: Warzone, Minecraft, Apex Legends (cross-play and cross-progression since 2022/2023; verify dates).

---

## 15. Checklists and Worked Examples

### 15.1 Competitive design review

- [ ] Every ability has defined counterplay and telegraphs proportionate to power.
- [ ] Multiple skill axes expressed; high ceiling, low floor.
- [ ] Snowball risk analyzed; comeback mechanisms tested.
- [ ] Randomness is input-level, bounded, and skill-preserving.
- [ ] Death/defeat explanations available (killcam, recap, replays).
- [ ] Spectator and caster tools planned.
- [ ] Matchmaking goals prioritized (fairness, queue time, ping, party handling).
- [ ] Ranked displayed and hidden ratings defined; smurf plan present.
- [ ] Netcode model chosen; latency budget stated; abilities tuned to it.
- [ ] Anti-cheat plan and server-authority boundaries defined.
- [ ] Reporting, muting, penalties, and positive reinforcement planned.

### 15.2 Co-op design review

- [ ] Players need each other (role/tool/info) yet can recover from a teammate failing.
- [ ] Everyone has meaningful contribution; visible credit.
- [ ] Works with strangers without voice (pings, auto-callouts).
- [ ] Scales difficulty with player count.
- [ ] Revive/rescue loops encourage helping.
- [ ] Loot rules prevent conflict.
- [ ] Friendly fire is configurable.
- [ ] Solo/AI fallback exists.

### 15.3 Worked example: fixing a toxic 5v5 shooter lobby

Symptom: high report volume mid-match; new players quit after D1.
Diagnosis: blame concentrated on low-kill players; open all-chat; no positive reinforcement; no role clarity.
Plan:
1. Make all-chat opt-in; team chat default on with filters.
2. Add a ping system for non-verbal comms.
3. Add post-match endorsements and highlight support/objective contributions.
4. Introduce graduated, immediate feedback for chat violations.
5. Add new-player protected queue for first 10 matches.
6. Measure: reports per 1,000 matches, repeat offender rate, D1/D7 retention for new players, and queue time impact.
7. A/B test each intervention, with guardrails (match completion, engagement).

### 15.4 Worked example: choosing netcode for a 2D fighting game

Requirements: frame-sensitive combos, 1v1, global players. Choice: deterministic simulation with rollback (GGPO-style). Implications: fixed timestep sim, serializable game state, fast resimulation (limit rollback frames, e.g., a budget in the 6-8 frame range as a heuristic; tune), cosmetic effects decoupled from sim state, latency-based matchmaking with ping caps, input delay as an option for poor connections, and a training mode with simulated lag for practice.

### 15.5 Worked example: designing a 4-player co-op roguelite

Roles: four classes with unique tools (e.g., barrier builder, scout/light, medic, heavy). Interdependence: doors need two simultaneous actions; fog-of-war reveals only to scouts; rescue mechanics. Reward structure: shared loot pool + personal upgrades. Difficulty: enemy count and elite frequency scale with players. Pickup viability: auto-pings, class-specific barks, and AI companion for missing players. Metrics: completion rate by party size, revive count per run, class pick rates, drop-in/out churn.

---

## 16. Common Pitfalls

1. Designing PvP without a plan for low-population hours and regions.
2. Trusting the client for outcomes that affect rank or economy.
3. Hard counters without counterplay; one-shot mechanics with no telegraph.
4. Punishment-only moderation (no positive reinforcement or education).
5. Ranked systems that publicize exact numbers and enable manipulation, or hide everything and breed distrust.
6. Using individual performance in rating, encouraging stat padding and anti-team behavior.
7. Ignoring party-versus-solo fairness.
8. Overfitting to the pro scene; ignoring casual experience.
9. Role queues with no incentive for scarce roles.
10. Netcode chosen late; design depends on frame-perfect inputs that online play cannot support.
11. Co-op where one player can do everything (alpha) or where one failure ends the run for all with no recovery.
12. No new-player path; veterans destroy novices.
13. Making all communication voice-dependent (accessibility, language, toxicity).
14. UGC platforms without moderation and legal processes.
15. Cross-play launched without input parity or anti-cheat considerations.
16. Matchmaking manipulation (engagement-optimized for spending) that hurts trust.
17. Treating toxicity as just "bad apples" and ignoring design triggers.

---

## 17. References

Inline citations use (Author Year). See references/13-bibliography.md for the master list.

**Papers and technical sources**
- Elo, A. E. (1978). *The Rating of Chessplayers, Past and Present*. Arco Publishing. Overview: https://en.wikipedia.org/wiki/Elo_rating_system
- Glickman, M. E. (1999). Parameter estimation in large dynamic paired comparison experiments. *Applied Statistics*, 48, 377-394. https://doi.org/10.1111/1467-9876.00159 Glicko summary: http://www.glicko.net/glicko/glicko.pdf
- Glickman, M. E. (2001/2013). Example of the Glicko-2 system. http://www.glicko.net/glicko/glicko2.pdf
- Herbrich, R., Minka, T., and Graepel, T. (2006). TrueSkill: A Bayesian Skill Rating System. *Advances in Neural Information Processing Systems 19 (NIPS 2006)*. https://papers.nips.cc/paper/2006/hash/f44ee263952e65b3610b8ba51229d1f9-Abstract.html
- Bernier, Y. W. (2001). Latency Compensating Methods in Client/Server In-game Protocol Design and Optimization. Valve (GDC 2001). https://developer.valvesoftware.com/wiki/Latency_Compensating_Methods_in_Client/Server_In-game_Protocol_Design_and_Optimization
- Valve Developer Community. Source Multiplayer Networking. https://developer.valvesoftware.com/wiki/Source_Multiplayer_Networking
- Gambetta, G. Fast-Paced Multiplayer: client-side prediction and server reconciliation. https://www.gabrielgambetta.com/client-side-prediction-server-reconciliation.html ; entity interpolation: https://www.gabrielgambetta.com/entity-interpolation.html ; lag compensation: https://www.gabrielgambetta.com/lag-compensation.html
- Fiedler, G. (Gaffer On Games). What Every Programmer Needs To Know About Game Networking: https://gafferongames.com/post/what_every_programmer_needs_to_know_about_game_networking/ ; Introduction to Networked Physics: https://gafferongames.com/post/introduction_to_networked_physics/ ; State Synchronization: https://gafferongames.com/post/state_synchronization/ ; Deterministic Lockstep: https://gafferongames.com/post/deterministic_lockstep/
- GGPO (Tony Cannon). Rollback networking SDK. https://www.ggpo.net/ ; overview: https://en.wikipedia.org/wiki/Rollback_netcode
- Booth, M. (2009). The AI Systems of Left 4 Dead. Valve (Artificial Intelligence and Interactive Digital Entertainment Conference keynote). https://steamcdn-a.akamaihd.net/apps/valve/2009/ai_systems_of_l4d_mike_booth.pdf
- Suler, J. (2004). The Online Disinhibition Effect. *CyberPsychology and Behavior*, 7(3), 321-326. https://doi.org/10.1089/1094931041291295
- Deutsch, M. (1949). A theory of co-operation and competition. *Human Relations*, 2(2), 129-152. https://doi.org/10.1177/001872674900200204
- Chen, Z., et al. (2017). EOMM: An Engagement Optimized Matchmaking Framework. *Proc. WWW 2017*. https://doi.org/10.1145/3038912.3052559

**Reports and websites**
- Anti-Defamation League. Hate Is No Game: Hate and Harassment in Online Games 2023. https://www.adl.org/resources/report/hate-no-game-hate-and-harassment-online-games-2023
- Fair Play Alliance (fairplayalliance.org): Positive Play resources.
- Riot Games news and dev blog (player behavior posts). https://www.riotgames.com/en/news
- Wikipedia: Apex Legends (ping system overview). https://en.wikipedia.org/wiki/Apex_Legends
- Deep Rock Galactic (Ghost Ship Games). https://www.deeprockgalactic.com/
- It Takes Two (Hazelight / EA). https://www.ea.com/games/it-takes-two

See references/13-bibliography.md for the master list.
