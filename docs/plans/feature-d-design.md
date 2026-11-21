# Feature D — Traces, cost attribution, and model routing

Use SQLite for local traces and `usage_records` for cost and quotas. Route delegated API work through `SubagentManager`, where both the built-in orchestrator and Claude Code’s GDW bridge already reach the same tools. Keep explicit model choices pinned and let callers opt into automatic selection with `tier = "auto"`. Export traces as OTLP/HTTP JSON using the existing `httpx` dependency. Phoenix requires a Collector to convert the payload to protobuf.

This is a read-only design. Function names in the findings refer to the current checkout. Interfaces, settings, routes, and commands marked as proposed are implementation work.

## 1. Findings and instrumentation points

Backend paths in this section are relative to `backend/gamedevworkstation/`.

| Span | Start and end | Data available |
| --- | --- | --- |
| Session turn | Start in `agent/loop.py:150`, `AgentRunner._run`, before `hooks.begin_turn`. End after `_turn_end` in the existing `finally` path. `_loop:259` dispatches every session harness from here. | GDW session ID, configured harness, elapsed time, and known termination reason. `_run` currently marks a normal return successful, including some early returns from `_loop` and the harnesses. Set explicit trace outcomes at effort decline, prompt-improver pause, gate exhaustion, and harness failure. |
| GDW subagent run | Start when `SubagentManager.spawn` in `features/subagents.py:195` has accepted the job, immediately before `create_task` at line 261. Use the same scheduling seam for the follow-up branch of `_register_tools.message:588`, which creates a new job with the same `sub.id`. End in `_run:266` or `_cancelled_before_start:504`, idempotently. | `sub.id`, `job_id`, parent session, provider, tier, model, effort, queue time, terminal status, and aggregate usage. `sub.id` is the existing spend-limit identity. `job_id` distinguishes executions of a resumed unit. |
| Built-in model attempt | The main loop streams once per iteration of `AgentRunner._stream_with_backoff` (`agent/loop.py:513`), and subagents call `complete` once per iteration of `SubagentManager._call_with_backoff` (`features/subagents.py:357`). Instrument the concrete `complete` and `stream` adapters in `providers/anthropic_provider.py:280` and `providers/openai_provider.py:270` so compaction, titles, prompt improvement, skill assistance, Review Desk, CI triage, and Eval Forge helpers are covered too. Open after `_prepare` authorizes the request. Close on the normalized response, error, or stream cancellation. | `ChatRequest` has the requested model, effort, output limit, and run ID. `Response` has normalized usage, model, stop reason, and latency (`core/types.py:182–224`). App-level retries produce separate spans. Both provider clients configure SDK-internal retries, so a span represents one GDW-issued request, which may contain multiple HTTP attempts. |
| Tool dispatch | Wrap `AgentRunner._run_tool` (`agent/loop.py:564`), `SubagentManager._tool` (`features/subagents.py:344`), and `GdwMcp.call` (`features/gdw_mcp.py:159`) from entry to outcome. Add a default span to `ToolRegistry.run` (`agent/tools.py:204`) for direct callers such as hooks and `UnityBridge`. Give those three dispatchers an explicit way to suppress the registry span for the same invocation. | `ToolContext` provides session, run, and caller role. Main and subagent call sites have the tool-use ID, although `_tool` currently receives only the name and arguments. Record policy denials, `ToolOutput.is_error`, success, and cancellation. `run_pre_tool` and `run_post_tool` in `features/hookbus.py:392–415` are optional and can receive raw arguments and output. Keep them inside the dispatch span. |
| MCP request | In `MCPManager.call` (`features/mcp_feature.py:635`), begin the outbound `tools/call` span at the `c.session.call_tool` await on line 669 and end on reply, timeout, cancellation, or error. The surrounding tool span covers approvals and connection acquisition. Instrument `initialize` and `list_tools` in `MCPConnection._run:321` at their own awaits. Trace the inbound `tools/call` in `GdwMcp._one` (`features/gdw_mcp.py:232,255–260`) after authentication and argument shape validation, around `self.call`. | MCP operation, direction, safe tool identity, transport where known, and structured error status. Direct Unity calls also reach `MCPManager.call`. An approval refusal produces a tool span. An RPC span requires an RPC dispatch. |

### External harnesses and existing exceptions

- **Claude Code.** `Harnesses.run` (`features/harnesses.py:177`) calls `ClaudeCode.run_turn` (`features/claude_code.py:1061`). Create an `invoke_agent` child marked `gdw.visibility = "harness"` for each actual user dispatch at `Proc.send:1140`. Close it on the matching `result`, process exit, cancellation, or interruption. Apply the same boundary to `_quiet_step:1206` and `HelperConv.ask:796`. `Proc._on_result:633` calls `record_usage:1516`, which already handles cumulative cost deltas across resume, per-turn tokens, and subscription billing. Put those usage counts on the harness invocation where available. Keep them off the enclosing session span so viewers can sum usage once.
- **Claude Code tool observations.** Pair tool-use IDs in `Proc._on_assistant:564` with tool-result IDs in `_on_user:613`. These times describe when GDW received the events. Mark unmatched starts `incomplete` at turn end. GDW bridge calls have their own measured server spans and share `gen_ai.conversation.id`. The bridge’s authenticated callback gives GDW a session ID but supplies no reliable parent span or tool-use ID. Use independent roots there and suppress a duplicate inferred execution span for GDW bridge tools. The CLI reader also filters `parent_tool_use_id` events at line 446. CLI-owned subagent lifetimes, individual inference requests, internal retries, and exact per-model charges are unavailable through this stream. Injected results and late results keep their own known attribution and cannot close a newer human turn.
- **Agent SDK and Codex CLI.** Trace the `query` invocation in `Harnesses._agent_sdk:222` and each subprocess invocation in `_codex_turn:370` as harness spans, including a fresh attempt after a failed resume. SDK `AssistantMessage`/`UserMessage` blocks and Codex JSONL item events support observed tool timing when both endpoints are present. Use an observed completion marker when only the end is available. The SDK’s `ResultMessage` and Codex `turn.completed` already supply aggregate usage. `SubagentManager._run_codex_cli:384` gets the same treatment under its GDW unit span.
- **Effort and usage.** `core/effort.py:76` validates the effort and requires a run-bound grant for above-high. Both API adapters call it in `_prepare`. GDW subagents also check in `spawn`, and the session harnesses obtain approval through `AgentRunner._effective_effort:238`. At the app-controlled CLI dispatches, call `check_effort` with the returned grant and the same run ID, including resume retries and quiet sends. The external process owns its internal requests. Preserve existing usage writes, including harness aggregates. Record failed app-issued attempts once with returned usage if present and an unknown-usage outcome otherwise. A zero-cost failure row represents missing billable evidence when no usage was returned.
- **Direct provider calls.** `features/web_tools.py:51` issues `prov.client.messages.create` directly, outside `_prepare`, and only records success today. Instrument that existing call explicitly, add `check_effort("low", None, ctx.run_id)` immediately before dispatch, and record failures through `S.usage.record`. Preserve the existing search surcharge. The success-only paths in `agent/context.py:168` and `features/eval_cli.py:68` also need failure accounting. ElevenLabs and ComfyPlug are visible through tool and service boundaries (`features/elevenlabs_feature.py:255`, `features/comfyplug_feature.py:259`). Their existing usage records report credits or workflow activity. The remote workflow’s internal model nodes and charges are opaque to GDW.

## 2. Span model, storage, and export

### SQLite and the recorder

Use a dedicated `traces.sqlite3` in `config.data_dir()`. Keeping telemetry on a separate SQLite file means a stalled trace writer cannot acquire the application ledger’s write lock. Follow `db.py:432–486` with append-only migrations and a transactional `PRAGMA user_version` bump. Open and migrate the trace file in the worker. Failure to open or migrate it disables tracing for that process and reports a coarse diagnostic. Use `c.execute` per statement inside the migration transaction.

```sql
CREATE TABLE trace_spans (
  trace_id TEXT NOT NULL,
  span_id TEXT NOT NULL,
  parent_span_id TEXT,
  session_id TEXT,
  run_id TEXT,
  name TEXT NOT NULL,
  category TEXT NOT NULL,
  kind INTEGER NOT NULL,
  start_ns INTEGER NOT NULL,
  end_ns INTEGER NOT NULL,
  status INTEGER NOT NULL,
  attrs_json TEXT NOT NULL,
  dropped_attributes INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (trace_id, span_id)
);
CREATE INDEX trace_spans_session ON trace_spans(session_id, start_ns, span_id);
CREATE INDEX trace_spans_expiry ON trace_spans(end_ns);
```

The proposed recorder in `features/tracing.py` exposes `span(...)` for normal scopes, `capture()` for an immutable parent reference, and `start(..., parent=...)` for an invocation that ends in a different task. A span handle accepts typed metadata and an idempotent `end(outcome)`. Use random nonzero 16-byte trace IDs and 8-byte span IDs in lowercase hex. Capture wall-clock start time and calculate the end using monotonic elapsed time. Store outcome codes and omit exception messages.

Use one `ContextVar` for the current span reference and reset its token in `finally`. `asyncio.gather` and newly created tasks inherit the reference, so parallel tool calls get distinct child spans. Capture the parent when scheduling a subagent and open its run scope inside its task using the saved reference. A background run can outlive its parent. For Claude Code, the persistent `Proc.reader` starts at `features/claude_code.py:339` and survives multiple turns. Store the invocation handle and usage scope on the corresponding `Turn` object and use them explicitly in reader callbacks. Clear them with the matching turn. Correlate separate authenticated HTTP callbacks by session.

### Attributes and redaction

| Span | Attributes |
| --- | --- |
| Session turn and subagent run | `gen_ai.operation.name = "invoke_agent"`, `gen_ai.agent.name` using a fixed role name, `gen_ai.conversation.id` using GDW’s session ID, and `gen_ai.request.model` when a single configured model applies. Use `gdw.harness`, `gdw.role`, `gdw.run.id`, `gdw.job.id`, and `gdw.outcome` for app metadata. |
| Model client | `gen_ai.operation.name = "chat"` for conversational inference, `gen_ai.provider.name` (`anthropic` or `openai`), `gen_ai.request.model`, `gen_ai.request.max_tokens`, `gen_ai.response.model` when reported and safe to emit, and `gen_ai.response.finish_reasons` from normalized enums. `gen_ai.usage.input_tokens` uses `Usage.total_input`, and `gen_ai.usage.output_tokens` uses `Usage.output_tokens`, which already includes reasoning. Add `gen_ai.usage.cache_read.input_tokens`, `gen_ai.usage.cache_creation.input_tokens`, and `gen_ai.usage.reasoning.output_tokens` where measured. Omit usage attributes when usage is unavailable. |
| Tool and MCP | `gen_ai.operation.name = "execute_tool"` and `gen_ai.tool.name` when a safe identity is available. Use `mcp.method.name` on protocol spans and `CLIENT` or `SERVER` for direction. MCP discovery only carries the protocol operation. Map errors and denials to bounded `error.type` and `gdw.outcome` values. |

Use the upstream names and document the semantic-convention revision in the instrumentation scope. Harness spans may carry aggregate token attributes when the harness reports them. A CLI’s configured model belongs in `gen_ai.request.model`. Actual response model attribution requires a model identity the response genuinely reports. [OpenTelemetry inference conventions](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/client-inference.md), [agent spans](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-agent-spans.md), [MCP spans](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/mcp.md)

Build attributes from an allowlist of typed fields at the recorder, before an item enters the queue. Fixed names, registered built-in tool identifiers, known model identifiers, enums, counters, and GDW-generated opaque IDs are sufficient. Use generic labels for arbitrary subagent names, unknown model names, and user-configured MCP server or tool names. Keep credentials, headers, environment values, request and response bodies, prompts, tool arguments and results, paths, URLs, command lines, and exception strings out of the payload. Existing redactors include `features/claude_cli.py:57` and MCP secret handling in `features/mcp_feature.py:55–154`. Treat those as inputs to the leak tests. Their display-safe output never becomes trace metadata. Enforce the same allowlist for span names, SQLite rows, and OTLP payloads.

### Settings and backpressure

Add `tracing` and `model_routing` fields to `Config` (`config.py:126`) and to `TYPED_SECTIONS:260`, with defaults and examples in `backend/gamedevworkstation/default_config.toml` and `config.example.toml`. Keep v1 editing in TOML. `features/settings_routes.py:19,75–85` exposes `EDITABLE` sections through `/api/settings`, so adding a section there requires an explicit decision about its response fields and live reload.

| Proposed key | Default and behavior |
| --- | --- |
| `tracing.enabled` | `true`, capture local spans |
| `tracing.sample_rate` | `1.0`, sample once at the root and inherit for children |
| `tracing.retention_days` | `7`, with a hard ceiling of 100,000 retained spans |
| `tracing.otlp_endpoint` | `""`, export off. Otherwise use the full signal URL. Permit HTTPS and loopback HTTP. Reject embedded credentials, query strings, and fragments. |
| `tracing.otlp_headers_env` | `{}`, optional header name to environment-variable-name map. Resolve values in the exporter only. |
| `tracing.otlp_timeout_s` | `2.0`, bounded network timeout |

End a span with a nonblocking enqueue. Start with a 2,048-entry queue, at most 24 attributes and 2 KiB of attributes per span, and batches of 128. A dedicated local worker owns SQLite, prunes in small batches, and hands persisted spans to a separate bounded export queue. Queue overflow, SQLite errors, export failures, and sampling affect the trace only. Track drops and export failures as aggregate counters and serve a paginated trace view with an explicit missing-parent indicator. Use the existing `astart`/`aclose` extension lifecycle (`server.py:130`, `app.py:68–88`) with a bounded local drain on shutdown. Network work stays off the turn path. Tests should exercise a stalled writer and exporter with a bounded queue, and a cancellation while a span is open.

### Exporter decision

| Option | Trade-off |
| --- | --- |
| OpenTelemetry SDK plus `opentelemetry-exporter-otlp-proto-http` | Standard batching, propagation, and protobuf export, including direct Phoenix ingestion. GDW still needs its own SQLite sink and metadata filtering. The SDK and exporter add a dependency chain and frozen-build validation. `uv.lock:987` contains the transitive API package. `packaging/gamedevworkstation.spec:10–24` collects GDW’s feature modules and selected dependency packages. Measure bundle size and cold-start impact if taking this option. [Python HTTP exporter dependencies](https://github.com/open-telemetry/opentelemetry-python/blob/main/exporter/opentelemetry-exporter-otlp-proto-http/pyproject.toml) |
| **OTLP/HTTP JSON with existing `httpx`** | Recommended for v1. Reuse the same sanitized records for SQLite and the wire encoder. There is no new frozen dependency or SDK initialization. GDW owns a narrow encoder and a bounded, best-effort sender. |

POST `resourceSpans` / `scopeSpans` with `service.name = "gamedevworkstation"`, numeric enum values, hex IDs, decimal-string nanosecond timestamps, and typed `AnyValue` fields. Use `application/json`. Cap response bytes, disable redirects, and retry transient failures at most once with the same span IDs. Treat OTLP partial success as terminal for that batch and count rejections. Keep the local rows after an export failure. [OTLP/HTTP specification](https://opentelemetry.io/docs/specs/otlp/#otlphttp)

Langfuse accepts JSON at `/api/public/otel/v1/traces`, and Jaeger accepts JSON at `/v1/traces` on its OTLP HTTP receiver. Phoenix’s HTTP handler requires `application/x-protobuf` and returns `415` for JSON. For Phoenix, point GDW at a Collector OTLP/HTTP receiver and have the Collector forward via its protobuf OTLP/HTTP exporter. Document the relay and verify it with synthetic spans before claiming compatibility. [Langfuse ingestion](https://langfuse.com/faq/all/opentelemetry-logs-metrics-span-links), [Jaeger write APIs](https://www.jaegertracing.io/docs/2.dev/architecture/apis/), [Phoenix trace handler](https://github.com/Arize-ai/phoenix/blob/main/src/phoenix/server/api/routers/v1/traces.py#L405-L473), [Collector JSON receiver](https://github.com/open-telemetry/opentelemetry-collector/blob/main/receiver/otlpreceiver/README.md#writing-with-httpjson)

## 3. Cost attribution and quotas

`UsageTracker.record` (`backend/gamedevworkstation/usage.py:54–76`) inserts and publishes one record and updates the existing pause state. The ledger already stores `session_id`, `role`, `run_id`, `provider`, `profile`, `model`, `feature`, timestamps, usage, and cost (`db.py:61–88`). Migration v5 adds `billing`. `task_sessions` (`db.py:406`) is many-to-many and `TaskBoard.unlink` deletes a link at `features/task_board.py:795`. Joining every usage row to every current task link would multiply spend and change old totals on relink.

**Proposed attribution.** Add nullable `task_id` and `task_attribution` to `usage_records`, with an index on `(task_id, ts)` and a run index on `(run_id, ts)`. A `NULL` attribution state means the row predates this feature. For new work, use the most recent explicit task attachment if it still points to a linked task. `TaskBoard.attach:803` writes the task code as `messages.meta.task_context`. Resolve it to `board_tasks.id` through the current links. Otherwise use the only linked task, if there is one. Record `unlinked` or `ambiguous` for other cases. Keep the snapshot even if the session is later unlinked or the task is deleted.

Resolve once at turn start, when a unit without a parent scope is queued, or at standalone operation entry. Children inherit their parent’s snapshot. A resumed subagent execution uses the new parent’s task and keeps its existing `sub.id` spend meter. Use a usage context independent of trace sampling and pass it explicitly to persistent CLI callbacks. For work issued by a subagent’s tool, preserve `role = "tool"` and fill its run ID from the unit scope only where the caller supplied none. This includes existing tools like `web_search` that already pass the subagent’s run ID. Old rows remain usable for session, role, run, and model reports.

**Proposed local REST.** Register `features/cost_attribution.py` and `features/tracing.py` via `routes.py:20`. Reuse the authenticated `/api` router. Supply these reads:

- `GET /api/usage/attribution?group_by=task|session|role|run|model&since=…&until=…&task_id=…&session_id=…&role=…&run_id=…&provider=…&model=…`. Group in SQL using an allowlisted column map, parameterized filters, pagination, and separate totals over the complete filtered set. Return ledger USD, subscription-estimate USD, tokens, credits, and recorded attempt and failure counts. Return a model key of `(provider, model)`. Use `LEFT JOIN sessions` for labels and `LEFT JOIN board_tasks` on the saved task ID. Group runs by ledger `run_id`, without transcript reads or a join that multiplies cost across follow-up jobs.
- `GET /api/traces?session_id=…&limit=…&cursor=…` lists recent roots and recorder health. `GET /api/traces/{trace_id}` returns a bounded page of spans and parent IDs. These reads use the telemetry database only. Existing `/api/usage/session/{sid}` already splits API and subscription totals and remains the current session summary (`features/usage_routes.py:299–319`).

**Quota behavior.** Keep `[limits].global_daily_usd`, `[limits].session_usd`, `[delegation].subagent_spend_cap_usd`, and the current per-job spend check at `SubagentManager.spawn:208–216`. Add `[limits].task_usd = 0.0`, a lifetime cap per attributed task, with zero disabling it. Extend `UsageTracker.check` and `headroom` (`usage.py:155–185`) to use the same task scope and billed-row predicate as the ledger. Check immediately before each delegated request, backoff retry, and fallback. Recheck queued CLI units at launch and apply the headroom where a harness supports a budget parameter. For opaque CLI work, enforcement is at dispatch and when aggregate usage becomes visible. Subscription estimates stay out of spend-limit sums, and subscription-only Claude dispatch preserves its existing API-cap behavior.

Use `BudgetExceeded` for task caps so the existing main-loop budget message, spawn tool error, and subagent failed status surface it. For example, “Task00042 has reached its $5.00 spend limit. Raise `limits.task_usd` to continue.” With task quotas enabled, multiple linked tasks without a usable selection should ask the user to attach the intended task through `/task` before dispatch. Existing daily and session “Resume anyway” allowances continue to apply to their own scopes. The caps are admission checks against recorded spend. A single request or concurrent requests already in flight can carry spend past a cap.

## 4. Model router and measurement

### Selection and fallback

`SubagentManager.spawn:195–246` picks one tier, resolves a model, validates the provider, gates effort, and constructs the unit. `_loop:300–329` currently builds one provider and tool context for the entire run. Add a pure policy in `backend/gamedevworkstation/features/routing_policy.py`, called by the existing `subagents` feature. Select the initial candidate in `spawn` and bind the current provider adapter, profile, model limits, tool context, and request options from the selected candidate before each new attempt. The normal tool and Eval Forge both use `SubagentManager.spawn`.

Use the existing `job_type`, requested tier/provider, effort, granted tools, and `escalation_step`. The installed `skills/delegation/SKILL.md:28–71` provides the starting task classes and escalation guidance. The repository has no machine-readable difficulty field for delegated work. Use a closed vocabulary of recognized job types for automatic rules and use a conservative standard tier for unknown types. Update the installed skill to request `tier = "auto"` for covered work. Keep explicit tiers, `codex.cli`, and specialized existing callers such as `campaign_validate` pinned. When automatic routing is disabled, `auto` resolves to the corresponding standard API tier.

Proposed policy excerpt:

```toml
[model_routing]
enabled = true
max_escalations = 1
revision = "1"

[model_routing.rules.extract]
candidates = ["claude.fast", "claude.standard"]
check = "json_object"

[model_routing.rules.mechanical_edit]
candidates = ["codex.fast", "codex.standard"]
check = "non_empty"

[model_routing.rules.implement_feature]
candidates = ["codex.standard"]
check = "non_empty"
```

A rule’s candidates are the models judged eligible for that task class, ordered by increasing capability for escalation. Resolve them through `Config.resolve` and validate against `Config.models`, `ModelConfig.efforts`, context and output bounds, and the adapter’s advertised capabilities. Keep candidates in the chosen provider family in v1 so the session profile, data policy, and provider-specific history stay valid. Choose the eligible candidate with the lowest configured estimated cost using `providers/base.py:114` `compute_cost` and a shared input/output token estimate. Skip unpriced candidates in automatic selection. Use the conservative standard tier or report a configuration error if no candidate fits. The eligibility rules are the initial definition of “good enough.” Their outcome needs Eval Forge evidence.

- **Provider failure.** Run the existing same-model rate-limit backoff. For an eligible transient provider error after retries, or a context failure where the next candidate fits, switch to the next compatible stronger candidate. Authentication or missing keys, approval refusal, budget exhaustion, cancellation, policy denials, and refusals terminate or follow their existing user path. When a provider error interrupts work after tools have run, continue from the accepted history with the existing tool-use/result pairs. Rebuild the request and tool context for the stronger model. Do not replay executed effects.
- **Failed check.** Evaluate the configured deterministic check on the terminal response. `json_object` checks parseability and object shape for an explicitly structured job, and `non_empty` catches an empty completion. A failure triggers one stronger attempt with a fixed repair instruction identifying the check. Reuse the unit’s history and worktree, and count both attempts against the same turn and run caps. After the allowed escalation, mark the unit failed with the check name. The main loop’s `_pre_complete` hooks (`agent/loop.py:412`) are whole-turn gates. Existing `record_unit_outcome` (`features/subagents.py:679–687`) supplies an after-the-fact verdict for stats. Keep both behaviors and use the unit’s deterministic check for automatic fallback.
- **Effort and evidence.** Preserve the requested effort and bound approval token, check effort and spend before every dispatch, and keep one `app.usage.record` call per application attempt. Record `gdw.routing.policy_revision`, `gdw.routing.job_type`, `gdw.routing.selected_tier`, `gdw.routing.reason`, and `gdw.routing.escalation` on relevant spans. Add a short in-memory attempt summary to the unit for evaluation, which works with tracing disabled. `_record_stats:454` currently writes total unit cost under the unit’s one model. Mark multi-model runs with a new `delegation_stats.mixed_models` column and exclude them from legacy single-model success and average-cost comparisons. Per-model spend for both attempts remains available from `usage_records`.

### User-approved Eval Forge command

Add a proposed `gdw eval compare-routing` subcommand in `features/eval_cli.py`, beside `_run_cmd:149` and the current `run` parser at line 286. Its default mode only loads the suite and reports eligibility, both model policies, trial count, exclusions, and expected spending limits. It starts no model client, grader command, or trial. The user decides whether to invoke the paid mode. The following is the proposed command interface; the numeric values are examples.

```sh
gdw eval compare-routing --suite evals/suite --baseline-tier codex.standard \
  --job-type implement_feature --trials 3 --max-spend-usd 20

gdw eval compare-routing --suite evals/suite --baseline-tier codex.standard \
  --job-type implement_feature --trials 3 --max-spend-usd 20 --approve-paid
```

Use the same `builtin_agent` factory (`features/eval_run.py:214`) for pinned and routed arms. Both use the same prompt, effort, file tools, start commit, timeouts, and graders. Pass the explicit job type into the routed arm. Select an eligible deterministic code subset of Eval Forge in v1 and list exclusions, including tasks requiring Unity replay or a paid rubric. Use `run_trial:257` for the fresh checkout and final grading, and reuse `pass_at_k:84` and `summarize:321`. Keep the final grader’s hidden tests and outputs out of the router. A policy that picks the baseline tier for every task should report no selection change.

Serialize and interleave arms by task and trial. Pass the smaller of the trial’s `Limits.max_cost_usd`, the remaining approved batch allowance, and any active subagent cap into the existing run-cap check. Stop admitting work when the allowance is reached. Report it as a recorded-spend threshold with possible last-request overrun. Use full-precision ledger costs by trial session and include failed attempts and fallback. Retain paired trial records with policy revision, model choices, fallback counts, spend, latency, environment and grader failures, and pass outcomes. Report paired pass-rate and spend differences, pass@1 and pass@k, and the denominators. Claim savings at the same observed pass rate only when the comparable pass rates support it. Report small samples and incomplete pairs explicitly. The current Usage page’s `savings()` estimate reprices tokens at the orchestrator’s rates (`features/usage_routes.py:229`) and does not measure this outcome.

## 5. Smallest useful UI

Add a **Cost attribution** section to `frontend/src/pages/Usage.tsx` after the existing model summary. Reuse its date range, authenticated `get` helper from `frontend/src/lib/api.ts`, and styling. Provide a grouping control for Task, Session, Agent role, Agent run, or Model. Show ledger cost and subscription estimates in labeled columns and render legacy and ambiguous spend as separate rows. Add a **Recent traces** disclosure for a selected session with start time, duration, outcome, and trace ID. Flat rows with depth indentation are enough for the first release. Keep settings in the config files and keep existing budget messages in Chat and Jobs.

## 6. Risks and v1 limits

- **Visibility and price accuracy.** Harness and SDK aggregates have lower resolution than built-in attempts. Provider errors may consume unreported usage, and a configured model can differ from the resolved response model. Report measured scope and provenance explicitly. The ledger remains the source of the app’s USD estimates.
- **Concurrent spend.** Day, session, task, and run checks can admit concurrent work against the same remaining amount. Reservations, provider reconciliation, and invoice-grade caps are follow-up work. Preserve existing daily and session pause behavior.
- **Telemetry loss.** Worker backpressure, crashes, and short shutdown bounds can leave partial trees. Surface missing parents and drop counts. Defer durable export replay, tail sampling, external propagation, and a full trace explorer. Trace files expire independently of the usage ledger.
- **Routing quality.** Job types are coarse and format checks only validate structure. Defer learned routing, cross-provider escalation, arbitrary command checks supplied by agent prompts, and automatic reruns of failed paid benchmarks. The first evidence comes from a user-approved paired run.
- **Verification.** Use `tests/conftest.py:21–39` for isolated `GDW_HOME`, disabled Keychain and automatic CLI discovery, and scrubbed real keys. Follow `tests/test_review_desk.py:131–168` for fake providers and authenticated `TestClient` tests. Use fake streams, an HTTP mock or local receiver, and `encoding="utf-8"` for text files. This design did not execute tests, launch a receiver, or run any models.

## 7. Implementation split

Paths below are repository-relative. Backend files in the table are under `backend/gamedevworkstation/`. D2 owns the one edit to `routes.py` for both new route modules. The split targets two working days with the v1 limits above.

| ID | Files | Acceptance criteria | Pytest tests to add | Difficulty |
| --- | --- | --- | --- | --- |
| D1 | `db.py`, `config.py`, `default_config.toml`, root `config.example.toml` | An app DB at v5 upgrades in one transaction. Usage rows survive with legacy attribution, old delegation rows default to single-model, and the new indexes exist. Invalid setting types and ranges fall back through config validation. Zero task cap and empty export endpoint preserve current spend and network behavior. | `test_v5_upgrade_preserves_usage_and_delegation_rows`, `test_trace_and_routing_config_defaults_and_validation` | normal |
| D2 | New `features/tracing.py`, `features/trace_store.py`, `routes.py`, `app.py` | Local recorder starts and stops through app lifecycle. Parent IDs survive concurrent tasks. Only eligible metadata reaches SQLite or OTLP. Batches use valid OTLP JSON and bounded queues. A stalled sink does not delay a turn or stop the other sink. Trace reads paginate and identify missing parents. | `test_trace_context_isolated_across_parallel_tasks`, `test_trace_allowlist_rejects_secrets_before_storage_and_export`, `test_otlp_json_rejection_leaves_local_spans`, `test_stalled_trace_sinks_do_not_block_turn`, `test_trace_routes_paginate_and_flag_missing_parent` | advanced |
| D3 | `usage.py`, new `features/cost_attribution.py` | A saved task assignment survives unlink and relink. Multiple links cannot multiply spend. Ambiguous work under a task cap receives actionable `BudgetExceeded`. Subscription rows and daily/session resume behavior match current accounting. The API returns exact filtered totals independently of tracing. | `test_task_spend_snapshot_survives_relink`, `test_ambiguous_task_blocks_only_when_task_cap_is_enabled`, `test_task_cap_and_headroom_exclude_subscription`, `test_usage_attribution_totals_match_ledger` | hard |
| D4 | `agent/loop.py`, `agent/tools.py`, `agent/context.py`, `providers/{registry,anthropic_provider,openai_provider}.py`, `features/{mcp_feature,web_tools}.py` | Built-in turns, streamed retries, helper completions, refused tools, actual tools, and MCP calls have the specified boundaries. Dispatch and registry produce one tool-execution span per invocation. Direct web search checks effort and records success or failure once. Trace failures preserve tool and provider outcomes. | `test_builtin_turn_traces_stream_attempts_and_tool_children`, `test_mcp_refusal_has_no_rpc_span`, `test_direct_registry_call_emits_tool_span`, `test_web_search_gates_effort_and_records_failed_attempt` | hard |
| D5 | `features/{claude_code,harnesses,gdw_mcp}.py` | Consecutive turns on one Claude process have distinct trace and usage attribution. Late or injected results cannot steal a newer turn. CLI and SDK spans identify aggregate visibility and observed tool timings. CLI dispatch checks the existing effort grant. The authenticated bridge records a server span without copying credentials or guessing a parent. | `test_persistent_claude_reader_attributes_two_turns`, `test_injected_cli_result_does_not_end_newer_turn`, `test_harness_usage_is_aggregate`, `test_gdw_mcp_bridge_traces_without_auth_metadata` | advanced |
| D6 | New `features/routing_policy.py`, `features/{subagents,usage_routes}.py`, `skills/delegation/SKILL.md` | Auto selects the cheapest eligible configured tier, and pins preserve existing routes. A transient provider failure or deterministic check failure can escalate once without re-executing accepted tools. Both attempts share the cap and are recorded. API and CLI runs, follow-ups, and pre-start cancellation each close one run span. Mixed-model runs cannot skew single-model statistics. | `test_auto_route_chooses_cheapest_eligible_model`, `test_explicit_tier_and_cli_stay_pinned`, `test_failed_check_escalates_without_replaying_tools`, `test_fallback_rechecks_effort_and_run_cap`, `test_resumed_and_cancelled_units_close_distinct_spans`, `test_mixed_route_excluded_from_single_model_stats` | advanced |
| D7 | `features/{eval_cli,eval_run}.py` | Preview exits without constructing a model client or executing a trial. Approved mode compares two arms through the real router with fake providers in tests, reuses the same grading path, stops admitting calls at the spend threshold, and reports paired pass and spend outcomes including fallback cost. Existing eval commands still work. | `test_compare_routing_preview_never_starts_models`, `test_compare_routing_pairs_trials_and_counts_fallback_cost`, `test_compare_routing_stops_at_approved_spend_threshold`, `test_eval_rubric_records_failed_attempt_once` | hard |
| D8 | `frontend/src/pages/Usage.tsx`, `frontend/src/lib/api.ts` if types are shared | The existing page displays attribution for its selected date range, labels subscription and unattributed spend, and can inspect a session’s recent traces. Missing traces leave the usage panel usable. | `test_usage_page_attribution_and_trace_api_contract` using `TestClient`, plus a frontend test for the grouping control and empty trace state | easy |
## 8. Amendments (binding; they override anything above)

1. `skills/delegation/SKILL.md` must stay byte-identical. Do not edit it. `tier = "auto"` is available to callers and
   to config; the skill is not changed in this feature.
2. D5 is reduced for v1: one `invoke_agent` span (`gdw.visibility = "harness"`) per Claude Code / Agent SDK / Codex CLI
   turn, ended on result, exit, cancellation or interruption, carrying the aggregate usage the harness already reports,
   plus one SERVER span per authenticated inbound GDW MCP bridge `tools/call`. Pairing individual CLI tool-use and
   tool-result events into observed tool spans is deferred.
3. No paid or live model run happens as part of this work. `gdw eval compare-routing` is built and tested only with
   fake providers; its paid mode requires `--approve-paid` and the user runs it later.
4. Every model call keeps going through the effort gate (`core/effort.py` `check_effort`) and is recorded with
   `app.usage.record(...)` exactly once per application attempt.
5. Text I/O uses `encoding="utf-8"`. Tests never touch the real Keychain or real app data (tests/conftest.py).
6. Tracing fails open: a tracing error, a full queue or a dead exporter never fails or noticeably slows a turn.
