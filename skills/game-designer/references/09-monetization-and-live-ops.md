# Monetization and Live Operations

Business models, designing an economy around revenue, pricing and store design, KPI definitions and formulas, live-ops practice, community management, and the ethics and regulation of monetization. Pair with `04-balance-and-economy.md` (faucets/sinks, drop math) and `12-playtesting-and-analytics.md` (metrics, A/B tests).

## Table of Contents

1. [How to Use This File](#1-how-to-use-this-file)
2. [Business Models](#2-business-models)
   - [2.1 Overview table](#21-overview-table)
   - [2.2 Premium](#22-premium)
   - [2.3 Free-to-play](#23-free-to-play)
   - [2.4 Freemium, demos, early access](#24-freemium-demos-early-access)
   - [2.5 Subscription and services](#25-subscription-and-services)
   - [2.6 Ad-supported](#26-ad-supported)
   - [2.7 DLC and expansions](#27-dlc-and-expansions)
   - [2.8 Cosmetics](#28-cosmetics)
   - [2.9 Battle pass](#29-battle-pass)
   - [2.10 Gacha and randomized rewards](#210-gacha-and-randomized-rewards)
   - [2.11 Choosing a model](#211-choosing-a-model)
3. [Designing the Game and Economy Around Monetization](#3-designing-the-game-and-economy-around-monetization)
4. [Pricing and Store Design](#4-pricing-and-store-design)
5. [KPIs: Definitions and Formulas](#5-kpis-definitions-and-formulas)
6. [Live Operations](#6-live-operations)
   - [6.1 Content cadence](#61-content-cadence)
   - [6.2 Events](#62-events)
   - [6.3 Seasons](#63-seasons)
   - [6.4 Roadmaps](#64-roadmaps)
   - [6.5 LiveOps calendar](#65-liveops-calendar)
   - [6.6 Live-ops pitfalls](#66-live-ops-pitfalls)
7. [Community Management](#7-community-management)
8. [Ethics, Dark Patterns and Regulation](#8-ethics-dark-patterns-and-regulation)
   - [8.1 Dark patterns in games](#81-dark-patterns-in-games)
   - [8.2 Pay-to-win](#82-pay-to-win)
   - [8.3 Loot boxes: research and law](#83-loot-boxes-research-and-law)
   - [8.4 Platform and rating-board rules](#84-platform-and-rating-board-rules)
   - [8.5 FTC v. Epic (2022)](#85-ftc-v-epic-2022)
   - [8.6 Ethical F2P principles](#86-ethical-f2p-principles)
9. [Case Studies](#9-case-studies)
10. [Checklists](#10-checklists)
11. [Common Pitfalls](#11-common-pitfalls)
12. [References](#12-references)

---

## 1. How to Use This File

Use it when the user asks "how should this game make money", "what should the store/battle pass look like", "what metrics matter", "plan the first six months of live ops", or "is this monetization ethical/legal".

Evidence labels:
- **Established**: formal definitions, published law, documented events.
- **Industry practice**: common patterns, no guarantee.
- **Heuristic**: judgment; validate with your own data.

Hard rule of this skill: **do not quote benchmark numbers (retention, conversion, ARPU) from memory.** Benchmarks vary by genre, platform, region and year, and published figures date quickly. If the user needs benchmarks, point to current sources (e.g., GameAnalytics, Adjust, AppsFlyer, Sensor Tower, or Newzoo reports) and tell them to compare against their own genre cohort. Anywhere below that a number is given, it is a definition, a regulatory fact, or is explicitly marked as an example.

Design stance: monetization is a design constraint like any other. The best monetization is **a product of the same pillars as the game**: players pay for things they value, understood clearly, without feeling tricked. Short-term revenue extraction that burns trust shows up later as churn, bad reviews, regulation and platform scrutiny.

---

## 2. Business Models

### 2.1 Overview table

| Model | Player pays | Revenue timing | Design implications | Typical fit |
|---|---|---|---|---|
| **Premium (buy-to-play)** | Once upfront | Front-loaded (launch spike, long tail with sales) | Complete experience; content-for-price expectation; refunds and reviews matter | Narrative, single-player, indies, many co-op |
| **Free-to-play (F2P)** | Optional purchases | Continuous; few spenders pay most | Must keep free players happy (they are content/community); retention is king | Mobile, PC/console live service, competitive |
| **Freemium / demo / free weekend** | Free base, paid unlock | Conversion event | Base experience must sell the full game | Demos, "lite" versions |
| **Subscription** | Recurring fee | Steady (MRR) | Ongoing content flow; churn management | MMOs, services (Game Pass-style), some mobile |
| **Ad-supported** | Free, ads fund | Per impression/view | Ad placement vs flow; rewarded ads | Hyper-casual, casual |
| **DLC / expansions** | Paid add-ons | Episodic | Base game must be strong; avoid cutting content | Premium, live-service |
| **Cosmetics** | Paid skins, no power | Continuous | Art pipeline; identity expression | F2P competitive |
| **Battle pass** | Seasonal track, free + paid | Seasonal | Progress-driven; fair time requirements | Live-service |
| **Gacha** | Randomized rewards | Spikes with banners | Odds, pity, regulation; highest ethical risk | Collection RPGs |

Hybrids are the norm (e.g., F2P + cosmetics + battle pass; premium + DLC + cosmetics; subscription + microtransactions).

### 2.2 Premium

- **Pros**: honest price/value, no need to engineer retention for revenue; strong fit for authored experiences.
- **Cons**: launch-dependent, discoverability is hard, price anchoring (players compare per hour or against the market), and refund policies (e.g., on Steam, within two hours of playtime and fourteen days from purchase) mean the first two hours must hook.
- **Design implications**: first two hours = sales pitch; tight content; avoid padding; plan post-launch updates, sales cadence, and DLC with community goodwill.
- **Pricing**: regional pricing, launch discount strategies, bundles; price signals quality, but over-pricing a new IP hurts conversion. Test via wishlists/demos where possible.
- **Revenue curve**: front-loaded; sustained with sales events, expansions, ports and bundles.

### 2.3 Free-to-play

- **Core idea**: remove the price barrier to maximize the player base; a minority of players (spenders) fund everything. Requires a **large funnel**, strong early retention, and ongoing content.
- **Value to non-payers**: non-payers provide population (matchmaking, social presence), word-of-mouth, content consumption, and ad value. In competitive multiplayer, they are the game's ecosystem; do not treat them as second-class.
- **Segments** (common labels, used as shorthand): non-payers, minnows (small spenders), dolphins, whales (very large spenders). Revenue is often concentrated in a small share of payers; the exact distribution is game-specific. Whales are a business reality and an ethical risk (see 8).
- **Sinks of effort**: F2P economy design requires currency flows, sink/faucet balance, and monetization hooks that add value without breaking progression (see 3).
- **Time-to-first-purchase**: shape first purchase as a low-friction, low-price, high-value "starter pack" entry; the first purchase strongly predicts later purchase (industry practice; validate).

### 2.4 Freemium, demos, early access

- **Freemium** often means "free core with paid expansion of capabilities" (including free-to-play but also "lite" versions). The base must be fun and complete as a taste.
- **Demos / Steam Next Fest** drive wishlists; demo design = vertical slice that ends on a hook. Conversion = demo players who buy or wishlist.
- **Early access**: community-funded development; success needs a playable, fun core, transparent roadmap and regular updates. Risk: public reception while unfinished; promises become debt.

### 2.5 Subscription and services

- **Types**: game-specific subscription (MMO sub, VIP pass), platform library subscriptions (the publisher is paid by deal or by engagement), and "plus" tiers offering conveniences (extra storage, XP boost).
- **Design needs**: constant value delivery (new content every few weeks), anti-churn design (progress tied to season, social obligations), cancellation that is easy to find (also a regulatory expectation in many jurisdictions - as of 2025 the FTC "click-to-cancel" (Negative Option) rule was vacated by the US 8th Circuit Court of Appeals in July 2025, but subscription cancellation enforcement continues via ROSCA and state auto-renewal laws such as California's, plus consumer law in the EU/UK; verify current rules).
- **Metrics**: monthly recurring revenue (MRR), churn rate, lifetime (1 / churn), and cohort retention.
- **Subscription + F2P** hybrids (e.g., VIP) must keep non-subscribers competitive in PvP.

### 2.6 Ad-supported

- **Formats**: interstitial (between sessions), banner, rewarded video (opt-in for in-game benefit), offerwalls (watch/install for currency).
- **Principles**: rewarded ads are better received than forced ones; place after natural breakpoints (level end), cap frequency, never interrupt active play, never trick users into clicking, make skippable rewards optional, and protect kids (COPPA/GDPR-K and platform family policies).
- **Revenue estimation**: eCPM x impressions per DAU; ARPDAU often from ads + IAP combined.
- **Risk**: dependence on ad networks and privacy changes (e.g., platform tracking rules reduce targeting and eCPM); quality-of-ads damage brand.

### 2.7 DLC and expansions

- **Expansion** = significant content (new region, campaign); **DLC** = small packs; **season pass** = prepaid bundle of future DLC.
- **Principles**: do not cut content from the base game to sell later (players detect it); price relative to content volume; ensure that content for all players (free updates) and paid content don't fragment the community (map packs in multiplayer split matchmaking - a documented issue in older shooters, hence the modern pattern of free maps funded by cosmetics).
- **Live-service expansions** (e.g., MMO expansions, *Destiny*-style annual releases) combine a story drop with systems resets; plan the technical and design debt.

### 2.8 Cosmetics

- **Why they work**: self-expression (autonomy), status (relatedness), no gameplay impact (fair), unlimited art content scale.
- **Design needs**: readable at a distance and in combat (cosmetics must not obscure gameplay signals - e.g., competitive shooters restrict skins' silhouettes and effects), ownership display (inspect, locker, showcase), social visibility (lobbies, kill-cams, emotes), and rarity taxonomy.
- **Risk**: if cosmetics are the only content, the game stagnates; if art gets systematically gated by luck, you've created gambling (see 8.3).
- **Conventions**: per-item direct purchase (not only random), bundles, cross-compatibility (a skin across modes), theming that fits the world's fiction (tone drift problem: crossover skins break fiction in some games and are embraced by others, e.g., Fortnite).
- **Resale/trading**: if players can trade, the market adds monetary value and exposure to fraud, laundering and gambling third parties (CS skin markets are an example; handle with care).

### 2.9 Battle pass

Pattern: a seasonal progression track with a free tier and a paid premium tier (sometimes multiple); players earn XP by playing or completing challenges; rewards unlock at levels. Popularized in *Dota 2* (The International compendiums) and mainstream via *Fortnite* (2017 Season 2 Battle Pass).

Design considerations:
1. **Value perception**: rewards clearly listed up front; premium rewards visible; many passes grant enough in-game currency to buy the next pass (a pattern in Fortnite-like passes - confirm for the game in question).
2. **Time pressure**: seasons end; unfinished tracks are lost. This is FOMO (see 8). Mitigations: reasonable completion time (state as target hours/week for typical player, e.g., a goal such as "completable at 45-60 minutes/day" - heuristic to calibrate), catch-up XP, extended tail, return of past content in a "vault" or a tier-skip pricing.
3. **Challenge design**: weekly vs daily challenges; avoid dailies that punish missing a day (use weekly with flexibility); challenges should encourage varied play but not force boring play.
4. **Reward types**: cosmetic-first; avoid gameplay power for pay; provide currency/boosters sparingly.
5. **Pricing/tiering**: Basic pass; premium bundle with tier skips; gift option (social).
6. **Free track matters**: it keeps non-payers engaged and gives payers a "why".
7. **Retention effect**: the pass acts as a goal structure (goal gradient) and as a commitment device (sunk cost). Design it as meaningful goals, not guilt.
8. **Season length**: typically ~8-12 weeks in many games (industry practice); too short feels grindy; too long loses urgency.
9. **Content pipeline**: each pass is a content production line (art, themes, narrative). Plan 2-3 seasons ahead.

### 2.10 Gacha and randomized rewards

- **Definition**: spend currency for a randomized pull from a prize pool (characters, weapons). Prevalent in collection RPGs (e.g., *Genshin Impact*, *Fate/Grand Order*).
- **Core mechanics**: rate tables (base rates by rarity), **pity systems** (guaranteed rare after N pulls, "soft pity" where odds ramp up before the hard cap), **rate-up banners** (featured item with boosted odds), **50/50** coin flips on the featured item with carryover guarantee, **duplicate** handling (conversion to currency or upgrade resource), **tickets/multi-pulls** (discount for 10-pulls).
- **Expected cost math**: With a constant per-pull probability p, expected pulls to first success = 1/p; with a hard pity at N the expected pulls are less than 1/p when p is small. Soft-pity models use a ramping p(n). Use `python scripts/design_calc.py --help` for drop odds and pity timer calculations. Always compute **the cost to guarantee** a featured item (worst-case) and the expected cost, and show both internally. See `04-balance-and-economy.md`.
- **Design risks**: outcomes uncertain relative to price (gambling-like); heavy reliance on spend for collection; regulatory exposure (odds disclosure laws in China and platform policies - see 8.4; some jurisdictions treat paid random items as gambling).
- **Player-friendly design**: published odds (including the effect of pity), generous pity, ability to target-purchase or exchange (shop to buy the desired item at a fixed price), free pulls from gameplay, no time-limited exclusive power that cannot return, and a clear spending cap and parental controls.
- **Gacha vs lootbox**: gacha is typically tied to collection and sometimes disclosed; loot boxes in a competitive game affect fairness and appear in games with minors.

### 2.11 Choosing a model

Decision guide (judgment, not law):

| If the game is... | Lean toward | Because |
|---|---|---|
| Authored, 5-40 hr, single-player | Premium (+ optional DLC) | Experience completeness; spend-wide audience |
| Co-op for 2-4 friends | Premium + free updates + cosmetics DLC | Friend groups buy together; no matchmaking split |
| Competitive PvP needing large populations | F2P + cosmetics + battle pass | Population is the product; fairness needed |
| Persistent online world with rich content | Subscription or buy-to-play + expansions | Predictable revenue funds content |
| Short-session mobile | F2P with ads/IAP or premium-paid-once for niche | Platform expectations |
| Collection-driven RPG | F2P with gacha *only if* you accept ethical and regulatory costs; else direct-purchase shop | See 8 |
| Jam/prototype/portfolio | Free or pay-what-you-want | Reach |

---

## 3. Designing the Game and Economy Around Monetization

Monetization should be integrated at the pillar level, not bolted on.

### 3.1 Principles

1. **Define what you sell** before building: time, convenience, content, expression, access, or power. Selling expression and content is the most defensible; selling convenience is common (skips); selling power is pay-to-win in competitive contexts (see 8.2); selling time-skips can invert incentives (see below).
2. **Incentive alignment**: if revenue rises when the game is more frustrating (waiting timers, scarcity), the design incentives are misaligned. Check by asking "what would the monetization team want to make worse about the game?"
3. **Separate currencies by purpose**: soft currency (earned) for gameplay economy; premium currency (bought, optionally earned) for convenience and cosmetics. Obfuscation risk: see 8.1.
4. **Economy flows**: map faucets (sources), sinks, and storage; ensure that premium-bought items do not trivialize the free economy; track inflation; see `04-balance-and-economy.md`.
5. **Timers and energy**: energy systems throttle consumption of content; they are monetized by refills. They create sessions rhythm but can harm autonomy. Prefer soft gating (rested bonuses, daily first-win boosters) over hard blocks; give generous caps.
6. **Progression speed**: free-player time-to-meaningful-goal should be reasonable; define target hours for key milestones and compute the paid acceleration (e.g., "pays 2x speed"). Heuristic: paid acceleration is ethically safest on non-competitive progress and cosmetics.
7. **Social dynamics**: gifting and clan-based spending increase retention; ensure that paid advantages do not create toxic hierarchy.
8. **Sink design**: cosmetics, customization, upgrades, consumables, repairs, crafting costs. Premium sinks (paying for convenience) are fine; mandatory premium sinks are not.
9. **Content vs systems**: monetize repeatable-value content (maps, characters) carefully; avoid selling advantages that make the free game obsolete.
10. **Compliance by design**: store odds disclosure, parental gating and spending limits, refund flows, region-specific adaptations (see 8).

### 3.2 Wallet and value perception

- **Display real prices** where possible; if premium currency is used, show its cost conversion; avoid bundle sizes that leave leftover currency after typical purchases (a known dark pattern - 8.1).
- **Value ladders**: smallest purchase meaningfully useful; mid-tier best "value per unit"; top-tier bundles reasonable, not misleading anchors.
- **First purchase offers**: one-time starter pack priced low; do not let players feel they must buy to proceed.
- **Contextual offers** (offer appears when it solves a felt problem, not when the player is most frustrated or after a loss streak) - the difference between help and exploitation.

### 3.3 Design patterns by genre (industry practice)

| Genre | Common monetized items | Ethical notes |
|---|---|---|
| Competitive shooter / MOBA | Cosmetics, battle pass, character unlocks (earnable) | Unlock-by-play parity matters; avoid selling stat power |
| Mobile RPG / gacha | Pulls, stamina, packs | Pity/odds clarity, spending caps |
| Casual puzzle | Lives, boosters, ad removal | Don't gate beyond difficulty walls designed to sell boosters |
| City builder / strategy mobile | Speed-ups, resources, builders | Timer pressure and PvP raiding make "pay to win" |
| MMO | Subscription, cosmetics, convenience | Time-gating, botting economy |
| Card game (digital) | Packs, direct crafting | Dust/crafting economy to reduce randomness |
| Survival / sandbox co-op | Premium + cosmetic DLC | Avoid selling shortcuts if the grind is the game |

---

## 4. Pricing and Store Design

### 4.1 Pricing principles

1. **Price points**: use conventional platform price tiers (e.g., $0.99, $4.99, $9.99, $19.99, $49.99, $99.99 on mobile) and regional pricing; match tier ladders with value; avoid prices that force leftover currency.
2. **Anchoring**: placing a high-priced item beside others raises perceived value of mid-tier items. Used ethically when the high-tier is genuinely sold and worth its price; unethical with fake "was" prices.
3. **Bundles**: combine items to simplify decisions and provide savings; show the savings calculation honestly.
4. **Discounts** : timing and frequency matter; permanent "50% off" erodes trust; seasonal sales in premium are standard.
5. **Price testing** : A/B tests on price points and bundle composition are routine in live games; for ethics, avoid personalized price discrimination exploiting vulnerable users, and disclose. Regional price differentials should use platform-supported purchasing power tiers.
6. **Sunk cost for bundles**: bundles of unwanted items push perceived savings; provide a la carte.
7. **Premium currency conversion**: avoid conversion rates that make the real price hard to infer; show the dollar equivalent for items.

### 4.2 Store UX

- **Hierarchy**: featured offer, personalized recommendations (based on play), categories, search, wishlist.
- **Clarity**: item preview (try-on, 3D), contents, rarity, price, duration of availability, whether duplicates are possible.
- **Time-limited rotating shops** (e.g., Fortnite item shop): create regular check-in cadence and scarcity; risk of FOMO; mitigate by re-running items or clear durations.
- **Purchasing friction**: confirm purchase, show balance after purchase, easy refund policy and parental controls, explicit price display, no accidental purchase paths (tap-to-buy with child accounts - the FTC Epic case concerned unintentional charges via single-button purchasing).
- **Free alternatives**: show how to earn the item in-game; highlight non-purchase paths.
- **No dark nagging**: cap number of pop-ups; never interrupt a match or session; avoid "shame" copy on decline ("No, I don't want to win") (confirmshaming).
- **Accessibility**: store text readability, no color-only rarity (see `08`).
- **Platform fees**: stores take a commission (commonly 30% standard, reduced tiers apply in some programs; confirm current terms); budget net revenue after fees, taxes, refunds and chargebacks.
- **Receipts and history**: purchase history accessible in-game.

### 4.3 Premium store page checklist (Steam-like)

- Capsule art, trailer in the first 10 seconds shows gameplay, short description w/ hook, tags, screenshots that show the real game, price and regional pricing, demo, wishlist call-to-action, accessibility features listed, content descriptors, and update cadence. Tie to marketing; see `01-design-process.md` for pitching.

---

## 5. KPIs: Definitions and Formulas

Define every metric precisely before reading it; "DAU" differs if "active" means "launched" or "played 1 minute".

### 5.1 Audience

| Metric | Definition | Formula / note |
|---|---|---|
| **DAU** | Unique users active in a day | Count distinct IDs with qualifying activity in 24 h (define "active") |
| **WAU / MAU** | Unique active users in 7 / 28-30 days | Windows are rolling or calendar; state which |
| **Stickiness** | How often MAU return | DAU / MAU (e.g., "DAU/MAU" ratio; higher = more habitual). Compare only within the same genre/definition |
| **Installs / new users** | New accounts or devices | Count of first-seen IDs |
| **Concurrent users (CCU)** | Users online simultaneously | Peak CCU, average CCU (PC and servers) |
| **Session length / sessions per day** | Engagement | Total session time / sessions; sessions / DAU |

### 5.2 Retention

- **Classic Day-N retention (DN)**: share of a **cohort** (users whose first-seen date = day 0) that is active on day N.
  `D1 = users active on day 1 / users in cohort` (likewise D7, D30). "Day 1" means the calendar day after install (state precisely; some use 24-48 h).
- **Rolling (return) retention**: share who return on day N **or later**; higher than classic.
- **Bracket retention**: active within a window (e.g., days 7-13).
- **Cohort analysis**: compare cohorts by install date, channel, version, or experiment; retention curves are plotted per cohort. A flattening curve (asymptote) suggests a stable core audience.
- **Churn** : `churn rate = users lost in period / users at the start of the period`; for subscriptions monthly churn; retention = 1 - churn. Expected lifetime in periods = 1 / churn (assuming constant churn).
- **Resurrection / reactivation**: lapsed users returning (event-driven).

### 5.3 Monetization

| Metric | Definition | Formula |
|---|---|---|
| **Revenue** | Gross bookings vs net revenue | Net = gross - platform fees - taxes - refunds/chargebacks (state which) |
| **ARPDAU** | Average revenue per daily active user | Revenue in the day / DAU |
| **ARPU** | Average revenue per user (all users in cohort/period) | Revenue / total users (state window) |
| **ARPPU** | Average revenue per paying user | Revenue / paying users |
| **Conversion rate (payer rate)** | Share of users who ever pay | Paying users / total users (cohort-based) |
| **Time to first purchase / D0, D7 conversion** | Speed of conversion | Distribution of days from install to first purchase |
| **LTV** (lifetime value) | Expected revenue per user over their lifetime | Cohort-based: sum of revenue per user over time (observed to day N, then projected). Simple model: `LTV ~ ARPDAU x expected lifetime in days`, where expected lifetime = sum of retention curve over days (area under the retention curve) |
| **CAC / CPI** | Cost per acquired (installed) user | Spend / installs (CPI = per install) |
| **ROAS** | Return on ad spend | Revenue attributed to cohort / ad spend (specify window, e.g., D7 ROAS) |
| **Payback period** | Days until cumulative LTV >= CAC | Read from cohort cumulative revenue curve |
| **Repeat purchase rate** | Payers who buy again | Payers with >= 2 purchases / payers |
| **Whale concentration** | Share of revenue from top x% payers | Compute from revenue distribution; monitor dependence |
| **Refund / chargeback rate** | Disputed share | Refunded orders / orders |

Worked example (illustrative numbers only, not benchmarks): Suppose a cohort of 10,000 installs; retention D1 = 40%, D7 = 15%, D30 = 5% (made-up). If ARPDAU = $0.10 and the area under the retention curve (expected active days in the first 30 days) is 4.5 days per install, then 30-day LTV ~ 4.5 x $0.10 = $0.45 per install. If CPI = $0.60, payback is not reached in 30 days; the lever is either improve retention, ARPDAU or lower CPI. Always model with your own data.

### 5.4 Quality and health

- **Funnel analysis**: tutorial start -> complete -> first session end -> D1 return -> first purchase. Identify the step with the largest drop.
- **Progression metrics**: level reached by D1/D7; time to level; sinks vs faucets by day (economy health).
- **Content consumption rate**: how fast cohorts burn content - informs cadence.
- **Social metrics**: friend count, party play share, guild membership; strong retention predictors in many games (validate in yours).
- **Support/complaint volume**: leading indicator.
- **Review score & sentiment**; store rating; NPS-like surveys.
- **Experiment metrics**: primary metric, guardrails (retention, complaints, refunds), sample size and duration pre-defined; see `12-playtesting-and-analytics.md`.

### 5.5 Reading metrics honestly

1. Compare like with like (same platform, geography, channel mix, version).
2. Beware averages: payers vs non-payers have wildly different distributions; use medians and percentiles.
3. Beware short-term optimization (revenue up, retention down).
4. Segment by acquisition source; paid UA cohorts behave differently from organic.
5. A/B test pricing and offers with guardrails and an ethics review.
6. Pair quantitative data with qualitative (surveys, community feedback) to explain *why*.

---

## 6. Live Operations

Live ops = running the game as a service after launch: content updates, events, balance patches, community, support, and monetization operations.

### 6.1 Content cadence

- **Layers of cadence** (industry practice): hotfixes (as needed), weekly rotations/challenges, bi-weekly or monthly events, seasonal major content (every ~8-12 weeks in many service games), and annual expansions. Choose a cadence your team can sustain; **a missed cadence damages trust more than a slower, reliable one**.
- **Content types**: new levels/maps, characters, modes, story chapters, cosmetics, limited-time modes, balance changes, QoL updates, systemic changes.
- **Content burn rate**: estimate time to consume vs time to produce; the gap determines whether you need replayable systems (procedural, competitive, social) rather than only authored content.
- **Production pipeline**: season planning 3-6 months ahead; feature-freeze, QA and cert windows; hotfix pipeline; feature flags and remote config to ship content without app updates.
- **Tech needs**: server-driven config, A/B framework, analytics, content scheduling tools, rollback, cheating detection, customer support tooling.

### 6.2 Events

Event types:
- **Limited-time modes (LTMs)**: new rules for a short period; test ideas; low cost to produce.
- **Collection / challenge events**: do X to earn Y; risk of grindiness.
- **Community goals**: shared global target (e.g., all players together defeat N enemies) - boosts relatedness.
- **Competitive events**: tournaments, leaderboards, cups.
- **Narrative live events**: world-changing moments (Fortnite's end-of-season live events are a prominent example of event-as-spectacle).
- **Collaborations / crossovers**: brand tie-ins to bring audience; check fiction fit.
- **Holiday / seasonal**: thematic.
- **Return events**: welcome-back for lapsed players.

Event design checklist:
1. Purpose (acquire, retain, reactivate, monetize, community)? Pick the primary.
2. Clear goal, duration, and rewards visible at entry.
3. Rewards: meaningful, mostly earnable without payment; avoid exclusive power.
4. Participation requirement is reasonable (hours estimate) and flexible (catch-up, no daily lock).
5. Avoid mandatory daily logins; design weekly goals.
6. Prepare tech: event config, rollback plan, load test, monitoring, support scripts.
7. Post-mortem: participation, retention effect, revenue effect, sentiment; feed into next event.

### 6.3 Seasons

- **Season structure**: a theme, a battle pass or progression track, new/changed content, balance resets (ranked reset), narrative beat, marketing beat. Seasons give predictable rhythm to players and to the studio.
- **Ranked seasons**: soft reset of ratings to compress; rewards at end; ensures population distribution stays healthy (see `10-multiplayer-and-social.md`).
- **Meta refresh**: each season changes the balance landscape (new items/weapons, rotation of maps); manage with transparency and patch notes.
- **Seasonal power resets** (RPG): resetting character power each season keeps new/returning players relevant (e.g., seasonal ladders in *Diablo*/*Path of Exile*-style leagues, which reset economies and encourage fresh starts).
- **Narrative arcs**: seasons as chapters keep coherence across cosmetics and events.

### 6.4 Roadmaps

- **Purposes**: align community expectations, sell the future, coordinate team.
- **Types**: public roadmaps (top-level quarters), internal roadmaps (detailed), "coming soon" teasers.
- **Principles**: promise less than you can deliver; label dates as targets; communicate slips early with reasons; deliver the big "pillar" items first; separate "committed" vs "exploring". Public roadmaps have been used well by *Path of Exile* (league announcements with detailed patch notes ahead), and poorly in titles where multi-year promises were missed and caused backlash (generic pattern).
- **Roadmap hygiene**: avoid selling future content before it exists (marketing and regulators); keep the post-launch plan separate from base-game value.

### 6.5 LiveOps calendar

A shared calendar prevents collisions and burnout. Example structure (illustrative):

| Week | Content drop | Event | Store | Community | Ops |
|---|---|---|---|---|---|
| 1 | Season launch | Launch event | New pass, featured bundle | Dev stream, patch notes | Server scale-up |
| 2 | Hotfix | Weekly challenges | Rotation | Feedback survey | Monitor KPIs |
| 3 | Mini-update (mode) | LTM | Discount pack | Creator spotlight | Balance pass |
| 4 | - | Community goal | Cosmetic drop | AMA | Ranked check |
| 5-6 | Balance patch | Cross-over | Collab bundle | Bug sprint | A/B tests |
| 7-8 | Mid-season content | Double XP weekend | Return bundle | Fan art | Cert prep |
| 9-10 | Season finale | Live finale | Final-week offers | Recap | Post-mortem |
| 11-12 | Off-season / prep | Comeback event | Sale | Roadmap reveal | Plan next season |

Calendar rules (judgment): never schedule a big monetized drop on the same day as a major content/bug-risky deploy; keep buffer weeks; avoid stacking multiple FOMO deadlines; put regulatory/holiday constraints (e.g., age-rated events, local holidays, store feature windows) on the calendar; staff on-call coverage for launch days.

### 6.6 Live-ops pitfalls

1. Content treadmill burnout: the team cannot sustain cadence; schedule off-weeks and automate pipelines.
2. FOMO stacking: overlapping limited-time pressures increase quit rate.
3. Meta whiplash: constant big balance changes without explanation.
4. Event rewards that cause economy inflation; test sinks.
5. Social erosion: not seeding community spaces.
6. Neglecting returners and new players: onboarding for new players must evolve with the content (the "new player cliff": years of accumulated systems).
7. Sunsetting poorly: end-of-life plans, refunds or offline modes (see "stop killing games" discussions as a consumer/regulatory topic, an ongoing area).
8. Not instrumenting events: no data to evaluate.

---

## 7. Community Management

Community is a design and business asset. It generates retention, free marketing, UGC and feedback, and it can also produce toxic dynamics and burnout.

1. **Roles**: community manager (voice of studio), community support/moderators, social media, creator/streamer relations, player support/customer service, developer relations (designers speaking directly), and data/insights liaisons.
2. **Channels**: official forums, Discord, Reddit, Steam community, social media, in-game news feed, patch notes, dev blogs, livestreams, and surveys. Choose channels where your audience is and keep an owned channel (email, in-game).
3. **Communication principles**:
   - Be **honest and timely**, esp. about bugs, outages and slips.
   - **Explain the "why"** of design/balance changes; transparency reduces conspiracy narratives.
   - **Listen at the pattern level**: vocal minority ≠ majority; weigh feedback by data and by player segments (ask who is speaking: top 1% grinders or the middle).
   - **Close the loop**: show what changed because of feedback.
   - **Set expectations**: "we heard you, we're investigating" vs promises.
4. **Patch notes**: structured (headline changes, balance with numbers and intent, bug fixes, known issues); credibility grows from detail (*Path of Exile*, *Warframe*, *League of Legends* publish detailed notes).
5. **Crisis management**: have a plan for outages, exploits, backlash. Respond quickly with a holding statement, then facts, then remediation (compensation for downtime), then post-mortem. Avoid defensive tone.
6. **Moderation**: clear code of conduct, tooling, escalation paths, and team wellbeing (moderator burnout is real). Align with in-game moderation (see `10-multiplayer-and-social.md`).
7. **Creators and streamers**: provide creator tools, early access, drops/rewards, content guidelines; watch for disclosure/ad rules (FTC endorsement guidance in the US).
8. **Beta and testing communities**: test servers, public test realms (PTRs), insider programs; set the rules (NDA/non-NDA), data collection consent.
9. **Player councils / feedback groups**: structured sessions with representative players.
10. **Community metrics**: sentiment, response time, forum activity, Discord activity, mention volume; pair with KPIs.
11. **Toxic community dynamics**: harassment of devs; set boundaries; protect staff; consider anonymous feedback intake.
12. **Respect for players' investments**: do not nerf in ways that invalidate expensive purchases without compensation; if you must, communicate and offer refunds/conversion.

---

## 8. Ethics, Dark Patterns and Regulation

### 8.1 Dark patterns in games

**Zagal, Björk and Lindley (2013), "Dark Patterns in the Design of Games"** (FDG 2013) adapt Harry Brignull's "dark patterns" (interfaces that trick users into things they did not intend) to games. Their definition (paraphrased): a dark game design pattern is one used intentionally by a game creator to cause negative experiences for the player that go against the player's best interests and are likely to happen without the player's consent. They distinguish dark patterns from "bad design" (accidental) by intent, and give examples including:

| Pattern (illustrative; names and wording paraphrased from memory of the paper, check the original for exact catalog) | Description | Note |
|---|---|---|
| **Grinding** | Repetitive tasks required to progress, sometimes monetized by skipping | Mitigate by making the grind purposeful and optional |
| **Playing by appointment** | Return at specific times or lose out (e.g., crops wither) | Daily/timed rewards; harms autonomy |
| **Social pyramid schemes** | Gain by recruiting friends | Spam invites, privacy abuse |
| **Monetized rivalries** | Competition fueled by spending | Leaderboards linked to purchases |
| **Pay-to-skip** | Pay to avoid annoyances the designer created | Check incentive alignment |

The paper's pattern list is longer; read it for the full taxonomy and the authors' discussion of intent and consent. Additional commonly cited dark patterns in game monetization (industry/academic discussion, not from that paper unless stated otherwise):

- **Infinite play / no stopping cues** (not from that paper): games engineered with no natural stopping points; provide stop points.
- **Locked-content teasing** (not from that paper): content shown as available but locked to tempt spending; keep display clear.
- **Obfuscated currencies / currency chains**: bundles never match prices, multiple currencies hide real cost.
- **Artificial scarcity / FOMO**: countdown timers, "last chance" banners that reset.
- **Loss-aversion hooks**: streaks that break if you miss a day; "your progress will be lost".
- **Confirmshaming**: guilt-inducing decline text.
- **Nagging and interrupts**: repeated offer pop-ups.
- **Pre-checked purchases / default opt-ins**, hidden subscriptions, hard-to-cancel flows (a "roach motel").
- **Targeting vulnerable players**: using spending/behavior data to push offers to likely compulsive spenders ("whale hunting"), targeting minors.
- **Fake social proof** and fake scarcity.
- **Rigged randomness**: undisclosed odds, "near-miss" displays, matchmaking that nudges players toward purchases (a concern raised by patents and speculation; treat as a reputational/regulatory risk if even perceived).
- **Pay-to-avoid-frustration** designs where the free path is deliberately bad (difficulty spikes designed to sell boosters).
- **Misleading marketing**: store page imagery that does not show real gameplay.

Test for dark patterns: (1) intent test - would we be comfortable explaining this mechanic to the player and a journalist? (2) consent test - does the player knowingly choose it? (3) vulnerability test - does it work better on children, compulsive gamblers or the cognitively tired? (4) reversibility test - can they back out?

### 8.2 Pay-to-win

- **Definition (descriptive)**: paying gives a **competitive advantage** over non-payers in a context where players compete (PvP) or where outcome determines status.
- **Variants**: pay-to-win (stat power), pay-to-skip (convenience), pay-for-power in PvE (less harmful but changes progression meaning), pay-for-information (e.g., seeing the map).
- **Why it hurts**: it undermines competence and fairness (SDT thwarting; see `08`), makes skill meaningless, kills trust, population health suffers when non-payers leave.
- **Safer patterns**: sell cosmetics, extra content, breadth (not power), and "convenience" that can be matched by time in a reasonable period; keep competitive modes level (normalized loadouts, earn-only unlocks).
- **Gray areas**: time-savers in competitive progression (character unlocks in a hero shooter), account boosts, and PvE power purchases that affect co-op parties.
- **Detect it**: ask whether a skilled non-payer can reach top ranks; track win rate by spending segment; watch community sentiment.

### 8.3 Loot boxes: research and law

**Research (peer-reviewed)**
- **Zendle and Cairns (2018)**, *PLoS ONE*: a large survey of gamers found a **link** between self-reported loot-box spending and problem gambling severity (correlation; causation direction is debated). doi:10.1371/journal.pone.0206767
- **Drummond and Sauer (2018)**, *Nature Human Behaviour*: analyzed 22 top-grossing games on app stores/Steam and found loot boxes to share structural characteristics with gambling; classified them with respect to gambling-like features and proposed which games contained them. doi:10.1038/s41562-018-0360-1
- **King and Delfabbro (2018)**, *Addiction*, "Predatory monetization schemes in video games (e.g. 'loot boxes') and internet gaming disorder": argues that certain monetization schemes (random reward, sunk costs, variable ratio, etc.) are "predatory" in that they exploit psychological vulnerabilities and may contribute to disordered gaming; calls for research and regulation. doi:10.1111/add.14286
- Interpretation: associations are consistent across studies, causality is contested; regulators have acted on the precautionary principle.

**Legal and regulatory landscape (as of the knowledge available; check current law)**
- **Belgium (2018)**: the Belgian Gaming Commission concluded that paid loot boxes in games such as *FIFA 18*, *Overwatch* and *Counter-Strike: Global Offensive* constituted illegal gambling under Belgian law, and advised the removal of paid loot boxes; some publishers removed them in Belgium and others did not comply fully (enforcement has been inconsistent).
- **Netherlands (2018 onward)**: the Dutch Gambling Authority (Kansspelautoriteit) assessed certain loot boxes and fined Electronic Arts over *FIFA* packs (2020 decision); in March 2022, the Council of State (Raad van State) overturned that fine, holding that the specific loot boxes did not meet the legal definition at issue, while the matter remains a policy discussion. Treat as an example of how legal definitions turn on specifics of the Dutch Betting and Gaming Act.
- **China (2017)**: requires publishers to disclose loot box drop probabilities.
- **Japan**: "complete gacha" (kompu gacha) was banned in 2012 (consumer protection reaction), and industry self-regulation requires odds disclosure.
- **South Korea**: introduced probability-disclosure requirements (in force around 2024 through the Game Industry Act amendment) - verify current details.
- **United Kingdom**: the government concluded in 2022 that it would rely on industry self-regulation (principles and technical measures) rather than classifying loot boxes as gambling - verify updates.
- **US**: no federal ban; the FTC held a loot box workshop (2019) and pursued dark pattern cases (see 8.5); several state bills have been proposed.
- **Australia**: classification rules were updated (2024) to impose age ratings for games with simulated gambling and loot box features - verify.
- Practical rule: **design globally compliant**: publish odds, avoid paid randomization for minors, provide spend controls, and keep region-specific toggles for compliance.

### 8.4 Platform and rating-board rules

- **Apple App Store**: Review Guidelines require apps offering "loot boxes" or other mechanisms that provide randomized virtual items for purchase to **disclose the odds of receiving each type of item** to customers prior to purchase (Guideline 3.1.1). https://developer.apple.com/app-store/review/guidelines/
- **Google Play**: Developer policy requires apps with paid randomized items to clearly disclose the odds of receiving those items in advance of purchase (Play Console "Real-Money Gambling, Games and Contests" and monetization policy pages).
- **Valve/Steam, Microsoft, Sony, Nintendo**: platform policies on odds disclosure for randomized purchases were introduced across consoles and PC around 2019 (consult each platform's current documentation).
- **ESRB (US/Canada)**: introduced the **"In-Game Purchases (Includes Random Items)"** interactive element label (2020) to indicate paid random items; the base "In-Game Purchases" label notes digital purchases generally. ESRB does not classify loot boxes as gambling.
- **PEGI (Europe)**: added the descriptor **"In-Game Purchases (Includes Random Items)"** (2020) along with "In-Game Purchases"; PEGI's descriptor system does not equate loot boxes with gambling, and the gambling descriptor applies to simulated gambling content. See https://pegi.info/what-do-the-labels-mean
- **Children**: COPPA (US), GDPR-K (EU/UK), Age-Appropriate Design Code (UK) and platform family policies restrict data use and targeted monetization toward minors; build parental controls and spending limits.

### 8.5 FTC v. Epic (2022)

In December 2022, the US Federal Trade Commission announced settlements with **Epic Games** (Fortnite) totaling **$520 million**: **$275 million** civil penalty for violating the Children's Online Privacy Protection Act (COPPA) through default-on voice/text chat for children and collecting data without parental consent, and **$245 million** to refund consumers tricked by **dark patterns** into unwanted purchases (e.g., a counterintuitive, inconsistent button configuration that let players incur charges with a single press, including while loading, in the item shop, and in some cases locking accounts of consumers who disputed charges). Source: FTC press release (Dec 2022), "Fortnite Video Game Maker Epic Games to Pay More Than Half a Billion Dollars over FTC Allegations of Privacy Violations and Unwanted Charges" (the original URL no longer resolves; search ftc.gov by title).
Lessons: default privacy-protective settings for minors, require clear confirmation for purchases, easy refunds, don't punish players for chargebacks, and review UI for accidental purchases. The FTC's 2022 staff report "Bringing Dark Patterns to Light" outlines the agency's view of dark patterns more broadly.

### 8.6 Ethical F2P principles

A practical set (my synthesis of industry practice and the literature):

1. **Respect the free player**: the free experience is a complete, fun game, not a trial of frustration.
2. **Sell what you would be proud to explain**: expression, content, convenience that is optional.
3. **No power for sale in competitive modes.**
4. **Transparent odds and prices**: publish rates (including pity), show real-money equivalents, avoid obfuscation.
5. **Offer direct purchase** alongside randomization, and pity/duplicate protection.
6. **Hard limits and parental tools**: spend caps, cooling-off, purchase confirmation, no purchases for unverified minors.
7. **No dark patterns**: no confirmshaming, fake scarcity, manipulative timers, or nagging.
8. **Don't target vulnerability**: no personalised offers keyed to spending spikes, losing streaks, late-night play, or detected compulsive behaviour; monitor for signs of harm and intervene (cooldowns, self-exclusion).
9. **Time-respecting design**: no mandatory daily chores; provide catch-up and a return path.
10. **Fair FOMO**: if limited, re-run or give another route; announce durations.
11. **Honest marketing**: advertise real gameplay.
12. **Make quitting painless**: easy cancellation, data export, honoring purchases at end-of-life.
13. **Treat whale dependence as a risk**, not a strategy: set internal spend alerts and ethical review for high-spenders.
14. **Measure harm**: track complaint, refund, chargeback and support contacts about spending, not just revenue.

---

## 9. Case Studies

Facts below are from public knowledge; verify specifics before citing in deliverables.

**Path of Exile (Grinding Gear Games, 2013)** - F2P ARPG. Sells cosmetics and **stash tabs** (convenience/storage) and supporter packs; the studio has long stated a "no pay-to-win" principle. Leagues (seasonal fresh-start economies every ~3-4 months) are a live-ops engine; extensive patch-note transparency and community dialogue (Q&A). Lessons: monetize convenience carefully (stash tabs are a pain-point sale; critics note this is "pay for QoL"), keep power off the store, and use league resets to refresh the economy. Random-reward elements exist in game systems but not as paid loot boxes for power.

**Fortnite (Epic Games, 2017)** - F2P battle royale; revenue from cosmetics via a rotating item shop, battle passes, and creator content; no pay-for-power. In 2019 Epic removed paid loot boxes in Save the World and, among other changes, publicly sells cosmetics directly. Live events (end-of-season spectacles), collaborations and a seasonal chapter structure drive attention. Legal case: FTC settlement for dark patterns/COPPA (see 8.5). Lessons: cosmetics + seasons scale; **purchase UX safety** matters; the game's brand identity (crossovers) can be a differentiator, but contributes to FOMO via a rotating shop.

**Genshin Impact (miHoYo/HoYoverse, 2020)** - F2P action RPG with **gacha** for characters and weapons. Published base 5-star rates, with a pity system (hard pity at 90 pulls for characters, soft pity ramping before; 50/50 mechanic for featured characters with a guarantee on the next 5-star; values as commonly documented by the developer's in-game odds pages - verify the current numbers). Offers free pulls from exploration, events, and the Battle Pass ("Gnostic Hymn"), plus Welkin Moon subscription-like monthly benefit. Lessons: heavy content cadence (6-week patches), strong free-player experience in single-player/co-op PvE (non-competitive limits P2W harm), but the structure still triggers criticism for spending potential on pulls and for pity opacity; **compute the cost to guarantee** and publish it internally.

**Warframe (Digital Extremes, 2013)** - F2P co-op action game. Monetized with **Platinum** (premium currency) that can also be traded between players (players can earn it by trading items), cosmetics, slots and convenience; all gameplay items can be earned through play (time vs money trade-off). Lessons: long-lived community via frequent updates (Devstreams), player trading creating an economy and a free-to-platinum path, and acknowledgement of grind (time as currency); caution: heavy onboarding complexity and a very deep economy.

**Hearthstone (Blizzard, 2014)** - F2P digital CCG. Monetized by card packs (randomized, with pity timers for Legendaries and card crafting through Dust to offset randomness) and adventures/expansions, plus a rewards track/battle-pass style system added later. Lessons: the **dust/crafting system** gives a deterministic path to desired cards; expansion cadence resets the meta; and free-player competitiveness depends on generous quests; criticism: cost to keep up with meta decks. Pack odds are disclosed in-game in accordance with platform rules.

Cross-case patterns: all successful cases pair **frequent content** with **community communication**; the strongest ones keep **power out of the store** or provide **deterministic paths**; and all have faced criticism when value or FOMO felt manipulative.

---

## 10. Checklists

### 10.1 Monetization design review

- [ ] What are we selling (time, convenience, content, expression, access, power)? Is it justified?
- [ ] Is the free experience complete and enjoyable?
- [ ] Are PvP modes free of purchasable advantages?
- [ ] Odds, drop rates and pity published and correct? Expected cost and worst-case cost computed?
- [ ] Prices shown in real money or clear conversions? No leftover-currency traps?
- [ ] Purchase confirmation, refunds, parental controls and spend limits present?
- [ ] Any FOMO? Could items return? Is the duration clear?
- [ ] Any daily-login pressure or streaks that punish absence?
- [ ] Any personalised offers using vulnerability signals? (remove)
- [ ] Complaint/refund tracking in place?
- [ ] Regional compliance review done (EU, UK, US, China, Korea, Japan, Australia)?
- [ ] Platform policy compliance (Apple/Google/Steam/console)?
- [ ] Rating-board interactive element labels set?

### 10.2 Live-ops readiness

- [ ] Content pipeline estimated 3 seasons ahead.
- [ ] Remote config and feature flags available.
- [ ] Event templates, calendar and approval process.
- [ ] Monitoring dashboards (KPIs, errors, economy).
- [ ] Rollback and hotfix procedures.
- [ ] Community channels staffed, moderation tooling and code of conduct.
- [ ] Roadmap and communication plan; patch note template.
- [ ] New-player and returner onboarding up-to-date.
- [ ] End-of-life / sunset policy drafted.

### 10.3 KPI dashboard minimum

Installs/new users by source, DAU/WAU/MAU, D1/D7/D30 cohort retention, session length and count, tutorial funnel, conversion and time-to-first-purchase, ARPDAU/ARPPU/ARPU, LTV curve vs CAC, economy health (currency in/out), crash rate, support tickets, review score.

---

## 11. Common Pitfalls

1. Bolting on monetization after the design is done; the economy and progression then conflict.
2. Optimizing short-term ARPDAU at the cost of retention and trust.
3. Treating whales as the business model; lack of ethical safeguards and concentration risk.
4. Unclear odds, obfuscated currency or a broken unit-price relationship.
5. Time gates that exist only to sell skips.
6. Selling power in competitive modes, then fighting community backlash.
7. Overly aggressive FOMO and stacking limited-time events.
8. A battle pass that demands unreasonable daily play.
9. Missing the live-ops cadence, breaking trust through broken promises.
10. Not instrumenting data, then guessing.
11. Using benchmark numbers from articles without matching genre, region and year.
12. Skipping compliance review for children, odds disclosure, and platform policy.
13. Confusing correlation with causation in retention (e.g., social features correlate with retention because engaged players use them).
14. Large content droughts followed by a "mega patch" that regresses quality.
15. Letting community toxicity or crunch drive staff burnout.

---

## 12. References

Inline citations use (Author Year). See references/13-bibliography.md for the master list.

**Papers**
- Zagal, J. P., Björk, S., and Lindley, C. (2013). Dark Patterns in the Design of Games. *Proc. Foundations of Digital Games (FDG) 2013*. http://www.fdg2013.org/program/papers/paper06_zagal_etal.pdf
- King, D. L., and Delfabbro, P. H. (2018). Predatory monetization schemes in video games (e.g. 'loot boxes') and internet gaming disorder. *Addiction*, 113(11), 1967-1969. https://doi.org/10.1111/add.14286
- Zendle, D., and Cairns, P. (2018). Video game loot boxes are linked to problem gambling: Results of a large-scale survey. *PLoS ONE*, 13(11): e0206767. https://doi.org/10.1371/journal.pone.0206767
- Drummond, A., and Sauer, J. D. (2018). Video game loot boxes are psychologically akin to gambling. *Nature Human Behaviour*, 2, 530-532. https://doi.org/10.1038/s41562-018-0360-1
- Kahneman, D., and Tversky, A. (1979). Prospect Theory: An Analysis of Decision under Risk. *Econometrica*, 47(2), 263-291. https://doi.org/10.2307/1914185

**Regulatory and platform sources**
- US Federal Trade Commission (Dec 2022). Fortnite Video Game Maker Epic Games to Pay More Than Half a Billion Dollars over FTC Allegations of Privacy Violations and Unwanted Charges. (The original press-release URL no longer resolves; search ftc.gov by title.)
- Apple. App Store Review Guidelines (3.1.1, loot box odds disclosure). https://developer.apple.com/app-store/review/guidelines/
- PEGI. What do the labels mean (descriptors incl. in-game purchases). https://pegi.info/what-do-the-labels-mean
- Belgian Gaming Commission. https://www.gamingcommission.be/
- ESRB. Ratings guide and interactive elements ("In-Game Purchases (Includes Random Items)"). https://www.esrb.org/ratings-guide/
- Wikipedia (overview, for pointers to primary sources). Loot box. https://en.wikipedia.org/wiki/Loot_box

**Tools and companion files**
- `scripts/design_calc.py` (drop odds, pity timers).
- references/04-balance-and-economy.md, references/10-multiplayer-and-social.md, references/12-playtesting-and-analytics.md.

Benchmark sources (look up current editions; not quoted here): GameAnalytics, Adjust, AppsFlyer, Sensor Tower, Newzoo annual reports.

See references/13-bibliography.md for the master list.
