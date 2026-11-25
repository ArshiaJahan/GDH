# What attracts game developers to GameDevWorkstation: market research (November 2026)

Internal research for the directors, not user documentation. Web research done 2026-11-24 by a
research subagent and checked by the session that added the `unity-practices` skill.

## How this maps to GDW today

| Priority | Already in GDW | Added on this branch (feat/unity-skills) | Still open |
|---|---|---|---|
| P1 verification first | compile-fix-loop, play-verify, headless-ops `RESULT:` checks | `unity-practices`: `cs_lint.py`, `texture_audit.py`, `RESULT:` lines in every check | API lookup before "done" for every Unity call |
| P2 cost control | spend limits, tiers, Usage page | Context card: skill tokens saved per call and per session, the session total at API list prices | cost preview before a task starts |
| P3 change safety | scene-prefab-safety, Changes card | debug scenes built by `DebugSceneBuilder`, which refuses while a scene has unsaved changes | one-click undo for scene and prefab edits |
| P7 fewer reloads | — | `scaffold.py` writes a whole kit before one recompile | batching agent edits |
| repeated work | — | `issue_cache.py`: a stored fix for a repeated issue costs one lookup | sharing the cache across projects |

Date: 2026-11-24. Method: web search plus a few page fetches. Many numbers come from secondary coverage or search snippets. "Unverified" means I could not confirm it against a primary source. "Accessed 2026-11-24" means the source has no visible date.

## Executive summary

- Game devs use AI for code but distrust it. Unity's report says 62% of Unity developers use AI for coding help and 5% use none (Unity, 2026-03-09). GDC's November 2026 report says 55% think generative AI harms the industry, and creative and player-facing content is "still largely off the table" (Game Developer, 2026-11-12). Position GDW as a back-end productivity tool for code, test, build and triage, not content generation.
- The top complaint is plausible but wrong output: invented Unity APIs, version drift (Unity 6 versus 2022), and scene/UI work that is slower to prompt than to do by hand. Stack Overflow's 2025 survey shows the general form: 66% name "almost right, but not quite" as their top frustration (The Decoder, 2025-07/08). Verification (compile, tests, console, doc lookup) is the wedge. GDW already has Unity CLI/batchmode, MCP and CI triage.
- Cost predictability is a live pain. Unity AI credits drain fast, with forum reports of trial credits gone in about 10 minutes, and Bezi credits are called hard to predict. GDW's usage tracking, spend limits and cost-tiered subagents answer this directly.
- Trust and IP concerns favour local-first designs. Devs worry cloud AI exposes NDA work and third-party assets (Unity forum, 2026-07). Local models, a clear data-flow statement and Steam-disclosure help are differentiators. Steam's January 2026 rewrite exempts behind-the-scenes dev tools. It still requires disclosure of AI content that players see or hear.
- The Unity MCP space is crowded and cheap: CoplayDev MCP for Unity is free MIT, Coplay Aura costs $10-$200 a month, Bezi $20-$180, and Unity AI is bundled into Unity plans. GDW should not compete on "an AI that edits the Editor". It should compete on orchestration: multi-model routing, cost control, record/replay playtests, review desk and CI.
- Engine-agnostic matters. Unreal now ships an official Unreal MCP, Godot has Ziva and open-source MCP servers, and Unity's share is only about 57-64% in JetBrains' survey. A skill-pack architecture can extend beyond Unity later, but Unity first is correct.
- Willingness to pay clusters at about $10-$20 a month for indies and about $100-$200 a month for heavy agent users. Unity Pro is $2,310 a year per seat, so studios pay per seat with budgets. Indies resist subscriptions with opaque credits.

## Prioritised recommendations

**P1. Verification-first loop for engine APIs ("never ship an invented API").** Force compile, console read, tests and doc/reflection lookup before an agent reports done. Show a pass/fail receipt.
- Why: hallucinated Unity functions are the most repeated complaint. One dev said they kept telling ChatGPT that a Unity function did not exist. Unity says APIs differ between Unity 6, 2022 LTS and older. A May 2026 article says one invented method can cost a day.
- Pain answered: hallucinated APIs and version drift.
- Sources: https://discussions.unity.com/t/chatgpt-4o-fails-at-unity-simulation-looking-for-real-alternatives-from-other-devs/1669133 (accessed 2026-11-24); https://unity.com/blog/47-tab-problem (2026-05); https://gamineai.com/blog/cursor-ai-pair-programming-unity-prototypes-practical-workflow-avoid-hallucinated-code-2026 (2026-05-07).

**P2. Spend limits, per-task cost previews and cost tiers as headline features.**
- Why: credit burn is the most visible grievance with Unity AI and Bezi. Unity docs put Agent-mode debugging at about 35 credits, planning at about 48, and complex refactors at 100 or more. Credits do not roll over. Unity forum users report trial credits used up fast.
- Pain answered: unpredictable cost.
- Sources: https://docs.unity.com/en-us/ai/credits/credits-about (accessed 2026-11-24); https://discussions.unity.com/t/ai-burned-all-my-trial-credits-with-2-simple-questions/1732505 (accessed 2026-11-24); https://makerstack.co/reviews/bezi-review/ (accessed 2026-11-24); https://discussions.unity.com/t/help-me-understand-the-value-of-claude-code-ai-inside-of-unity/1730304 (2026-07-07).

**P3. Change safety: preview, diff and one-click undo for scene, prefab and asset edits.**
- Why: the fear is that an agent "make[s] a mistake of set up / modify something I would not be aware of". Devs say AI is poor at scenes and UI. Voronoi kept a revert option when fixing an AR Foundation upgrade.
- Pain answered: broken scenes and prefabs, silent edits.
- Source: Unity forum thread, 2026-07-07 (URL above). Scene and prefab diffs and merge conflicts as an engine pain are unverified in this research.

**P4. Local-model and privacy mode with an explicit data-flow panel.**
- Why: forum voices warn that cloud AI may expose projects, third-party assets and NDA work and recommend local models. GDW already supports local models.
- Pain answered: IP, licensing and NDA worries.
- Source: Unity forum thread, 2026-07-07.

**P5. Steam AI disclosure helper (AI provenance ledger).** Log which assets came from ComfyUI or ElevenLabs and export a disclosure summary.
- Why: Valve's January 2026 form now targets AI content players consume, and dev-efficiency tools are exempt. Checking the boxes is an attestation, so provenance records help. One source says 40.1% of 2026 Steam releases disclosed AI by November 2, and that figure is self-reported and unverified.
- Pain answered: disclosure compliance and asset-licensing anxiety.
- Sources: https://www.pcgamer.com/software/ai/steam-updates-ai-disclosure-form-to-specify-that-its-focused-on-ai-generated-content-that-is-consumed-by-players-not-efficiency-tools-used-behind-the-scenes/ (2026-01); https://www.videogameschronicle.com/news/valve-has-significantly-rewritten-steams-rules-for-how-developers-much-disclose-ai-use (2026-01); https://tech-insider.org/steam-ai-disclosure-2026 (low quality, unverified).

**P6. Record/replay playtests with AI triage, positioned as "bots find bugs, humans judge fun".**
- Why: commentary says agents can confirm a car works but not whether it is fun. Modl.ai and Sauce Labs sell synthetic players, but I found no rigorous developer survey on this. The gap is an open, local, replayable workflow.
- Pain answered: no playtesting.
- Sources: https://decrypt.co/342085/study-ai-outpaces-humans-game-testing (accessed 2026-11-24); https://respawn.outlookindia.com/gaming/gaming-guides/will-ai-game-testers-shrink-qa-teams-in-the-gaming-industry (accessed 2026-11-24). Evidence is mostly trade and vendor sources.

**P7. Workflow polish for editor iteration: batch changes, then a single recompile or domain reload.**
- Why: Unity's own docs admit that waiting to enter Play mode slows development. Agents that trigger a reload per edit multiply that cost. Unity 6.6 docs say domain reload is skipped by default and recommend leaving it off.
- Pain answered: compile and reload time.
- Sources: https://docs.unity3d.com/Manual/ConfigurableEnterPlayMode.html (accessed 2026-11-24); https://discussions.unity.com/t/why-is-domain-reload-sooo-slow-and-will-this-ever-be-fixed/798176 (about 2022-era).

**P8. Multi-model routing and bring-your-own-key, with transparent pricing.**
- Why: tool prices are moving. Copilot reportedly moved individuals to usage billing on June 1, 2026. Claude Code's Pro-plan status is reported inconsistently. Skeptics expect current pricing to be subsidised and to rise. A router that picks the cheapest capable model protects users.
- Pain answered: cost and vendor lock-in.
- Sources: https://dev.to/pat9000/ai-coding-assistant-pricing-in-2026-copilot-vs-cursor-vs-claude-code-5h4d (accessed 2026-11-24, conflicting secondary sources); Unity forum thread, 2026-07-07.

**P9. Rider/VS/VS Code-friendly integration; do not demand a new editor.**
- Why: JetBrains' survey shows Rider is the top indie IDE (50%), Copilot use rose about 20 points since 2024, and only 9% of AAA and 16% of others already use coding agents (63% of AAA say they are very likely to try one within 12 months). A forum user prefers AI inside Rider.
- Pain answered: workflow friction.
- Sources: https://lp.jetbrains.com/the-state-of-gamedev-2025/ (accessed 2026-11-24, undated); Unity forum thread, 2026-07-07.

**P10. Engine expansion: Unreal and Godot skill packs after Unity is solid.**
- Why: Epic ships an Unreal MCP. Godot has Ziva and MIT MCP servers. Neither has a strong cost-control or review-desk layer (unverified, not tested).
- Pain answered: multi-engine teams.
- Sources: https://dev.epicgames.com/documentation/unreal-engine/unreal-mcp-in-unreal-editor (accessed 2026-11-24); https://ziva.sh/ (accessed 2026-11-24).

## Complaints and sentiment

| Theme | Evidence | Source (date) |
|---|---|---|
| Industry sentiment | 52% (Jan) then 55% (Nov) say generative AI harms the industry; use at work 36% then 40%. The two reports differ in sample size, 2,300 versus 2,600 respondents. | GDC via GamingOnLinux, 2026-01 and 2026-11 (https://www.gamingonlinux.com/2026/01/gdc-26-report-36-of-devs-use-generative-ai-while-28-target-steam-deck-and-8-linux); Game Developer 2026-11-12 |
| Unity usage | 62% use AI for coding; writing/narrative 44%; 5% none. Survey base about 300 devs. | https://unity.com/en/blog/2026-unity-game-development-report-trends (2026-03-09) |
| General trust | 84% use or plan to use AI; about 46% distrust accuracy (trust figures vary 29-33% by outlet); 66% "almost right"; 45% say debugging AI code takes longer than expected. | https://stackoverflow.co/company/press/archive/stack-overflow-2025-developer-survey/ (2025-07-29) |
| Hallucinations/version drift | Newer engine versions make general assistants worse (Godot). A single invented API can cost a day. | https://dev.to/ziva/7-godot-4-api-calls-your-ai-assistant-still-gets-wrong-3ep6 (accessed 2026-11-24); gamineai (2026-05-07) |
| Scene/UI weakness | AI is poor at UI and scenes; the last 20% takes most of the work; "comprehension debt". | Unity forum, 2026-07 |
| Cost | Credits burn fast; Bezi predictability complaints; "pricing is subsidised". | See P2 |
| IP/privacy | Cloud exposure of NDA and third-party assets. | Unity forum, 2026-07 |
| OSS maintainers | Hidden Folks developer says LLM-written PRs to Godot waste reviewer time (single anecdote). | https://games.mxdwn.com/news/godot-developer-says-ai-is-becoming-a-big-problem/amp (accessed 2026-11-24) |
| Playtesting | AI finds bugs but cannot judge fun (qualitative). | decrypt / Outlook Respawn (above) |
| Steam | Disclosure now centres on player-consumed content; tools exempt. | PC Gamer, VGC (2026-01) |

## Willingness to pay and pricing

| Product | Price | Note and source |
|---|---|---|
| Unity Personal | Free under $200k revenue and funding | https://unity.com/products/pricing-updates (accessed 2026-11-24) |
| Unity Pro | $2,310 a year or $210 a month per seat; 5% increase from 2026-01-12 | same source |
| Unity AI | $10 a month after 14-day trial; 1,000 credits (Personal), 2,000 (Pro), 3,000 (Enterprise) | search snippets; partly unverified: https://unity.com/products (accessed 2026-11-24) |
| Coplay Aura | Indie $10, Pro $40, Ultimate $200 a month; 2-week trial | https://coplay.dev/blog/aura-for-unity-v0-15-0-ai-agent-for-unity (accessed 2026-11-24) |
| Bezi | Pro $20 (800 credits), Advanced $60 (2,400), top tier $180-$200 (sources conflict; unverified) | https://makerstack.co/reviews/bezi-review/ (accessed 2026-11-24) |
| Ludus AI (Unreal) | Official docs say custom quote. G2 lists $10 and $25 a month (unverified). | https://docs.ludusengine.com/plans-and-billing (accessed 2026-11-24) |
| Ziva (Godot) | Free tier; Basic $20 a month | https://ziva.sh/ (accessed 2026-11-24) |
| Cursor Pro | about $20 a month (Ultra $200) | secondary: https://daily.dev/blog/ai-coding-tools-cost-cursor-vs-copilot-vs-claude-code-pricing/ (accessed 2026-11-24) |
| Claude Code | Max $100 or $200 a month; Pro-plan status conflicting | same family of sources; verify on vendor page |
| GitHub Copilot | Pro $10, Max $100 (usage-based since 2026-06-01, per secondary source) | https://dev.to/pat9000/ai-coding-assistant-pricing-in-2026-copilot-vs-cursor-vs-claude-code-5h4d (accessed 2026-11-24) |
| JetBrains Rider | about $509 first year commercial (reseller); non-commercial plan exists, price unverified | https://www.componentsource.com/product/rider/buy/1579094 (accessed 2026-11-24) |
| ClaudeUnreal (FAB) | $99 one-off, bring your own plan | https://claude.com/plugins/unreal-engine-skills-for-claude-code (accessed 2026-11-24, secondary listing) |

Reading: indie price points are about $10-$20 a month. Power tiers are $100-$200 a month. Unity Pro seats at $2,310 a year show studios already carry per-seat tooling budgets. I found no direct survey of game devs' willingness to pay for AI tools, so this is inferred from list prices (unverified as WTP).

## Engine pain points

- **Unity.** Domain reload and Play-mode entry waits are acknowledged by Unity. Reports include a 12-14 s lock for a 2 s compile (about 2022) and a Unity 6.0 bug report of long Play-mode entry. Unity 6.6 skips domain reload by default, which shifts static-state resets onto developers. Licensing trust after the runtime fee: Unity's 2026 plan page shows Personal at $200k with unlimited seats and Havok removed from 6.0 LTS Pro. I did not find 2026 sentiment data on trust (unverified). Prefab merge conflicts and serialization: no source found (unverified). Sources: Unity docs (above); https://discussions.unity.com/t/why-is-domain-reload-sooo-slow-and-will-this-ever-be-fixed/798176; https://discussions.unity.com/t/report-case-id-in-86490-unity-version-6000-0-22f1-takes-a-rather-extended-period-of-time-to-enter-play-mode/1535745 (accessed 2026-11-24).
- **Unreal.** Shader compilation and traversal stutter are the visible complaints. Epic added PSO precaching in 5.2, and coverage says UE 5.8 targets stutter after developer feedback (wccftech, accessed 2026-11-24). C++ compile times and build sizes: no 2026 source found (unverified). Sources: https://www.unrealengine.com/en-US/tech-blog/game-engines-and-shader-stuttering-unreal-engines-solution-to-the-problem (2025-02); https://wccftech.com/unreal-engine-5-8-tackles-stutter-problem-epic-listens-developers/.
- **Godot.** Adoption is growing: hobbyist use rose from 9% to 31%, with 18-19% of indie and AAA teams (JetBrains State of GameDev 2025, accessed 2026-11-24). General assistants lag on Godot 4 APIs (Ziva post). Console ports, GDScript tooling and C# support: no usable source found (unverified).

## Competitors

| Tool | What it does | Price | Gaps (my read, mostly unverified) |
|---|---|---|---|
| Unity AI (Assistant, Generators, agent) | In-Editor assistant and asset generation, credits | $10 a month plus credits; bundled allowances | Credit burn; Unity-only; one forum user says Coplay needed a Unity AI sub (single claim) |
| Coplay Aura | Editor agent for Unity | $10-$200 a month | Vendor-locked credits; no cross-model cost routing known |
| MCP for Unity (CoplayDev) | Open-source MIT bridge, 47 tool entrypoints, multi-instance, Roslyn validation; reportedly about 13.6k stars (snapshot date unclear) | Free | A bridge, not an orchestrator; GDW already uses it |
| Bezi | Unity assistant with project context | $20-$180 a month | Credit predictability |
| Cursor / Claude Code / Copilot | General coding agents, used with Unity via MCP or the IDE | $10-$200 a month | No engine awareness out of the box, no game-specific cost controls |
| Ludus AI | Unreal copilot | custom or unverified | Unreal-only |
| Epic Unreal MCP and community servers | Official and community editor bridges | Free to $99 | Bridge level only |
| Ziva and Godot MCP servers | Godot agent, local MCP | Free to $20 a month | Godot-only |
| Rosebud, Layer, Scenario | Not researched; unverified | n/a | n/a |

## Caveats

No Reddit threads were retrieved directly. Forum evidence is Unity Discussions only. Several pricing and statistics sources are aggregators; verify on vendor pages before publishing. The Unity report's "79% positive" stat is attributed to different years by different outlets and is not used here.
