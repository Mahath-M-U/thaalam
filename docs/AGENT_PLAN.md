# Agentic layer for Thaalam — Pydantic AI over the existing free-tier client

## Context

Thaalam's assistant today is a **single-shot RAG-shaped call**. `chat_service._prepare()`
builds one static grounding block from `chat_context.build_context()` — today's snapshot,
the page's insight sections, reads, vitality, runway — stuffs it into a system message, and
hands it to `llm_client.complete()` / `.stream()`, which walks a ranked list of OpenRouter
free models. One question, one model turn, one answer.

That design bought real things worth keeping: every figure is read server-side from DuckDB
so a crafted request cannot plant a false premise; the client sends a page key and a read id,
never numbers; the whole model-rotation walk finishes before the first token so a failure is
still an HTTP status. But it has a ceiling:

- **It cannot look anything up.** Whatever `build_context` chose to render is all the model
  will ever see. "How did my HRV behave in the two weeks around my last hard block?" has no
  path to an answer — that series is in DuckDB, and nothing fetches it.
- **It cannot take a second step.** No re-reading, no checking a hypothesis, no comparing two
  windows. Everything is one shot from one fixed block.
- **The prompt grows to cover every question.** `_PAGE_SECTIONS` plus the whole-picture tail
  means most of the analytics travel on every request whether or not they are relevant, which
  costs context and dilutes attention.
- **Nothing is typed.** `_extract_reply()` returns a bare string. There is no schema on the
  way out, so nothing downstream can check that a claim is grounded.
- **Nothing is measured.** No traces, no golden set, no way to tell an improvement from a
  regression.

**The intended outcome:** a small agent runtime that can *call the existing domain services
as tools*, take a bounded number of steps, and return typed, citation-carrying answers —
without adding a framework that outweighs the app, without leaving OpenRouter's free tier,
and without giving up the privacy, injection, or streaming guarantees the current design
earns.

**Decisions taken (from the pre-plan questions):**

| | Choice |
|---|---|
| Runtime | **Pydantic AI + in-house glue.** `llm_client.py` keeps owning free-model discovery, ranking and cooldowns; that ranked list feeds a `FallbackModel`. No LangChain, no LangGraph. |
| Order | **Features first**, eval harness after (Phase 6). |
| Budget | **Stay on the free tier**, engineered around: a gate that decides whether a question needs the loop at all, cached tool results, deterministic Python tools, and a fallback ladder back to today's single-shot path. |

## Why Pydantic AI and not LangChain/LangGraph

Thaalam has 13 runtime dependencies, one worker, and a hand-written 765-line OpenRouter
client with better free-tier instincts than any framework ships with. LangGraph would add
~50 transitive packages, measurable latency from its checkpointing layer, and force a rewrite
of rotation logic that already works. Pydantic AI is native to the stack already here
(pydantic 2 + FastAPI), and the pieces map one-to-one onto code that exists:

| Existing Thaalam code | Pydantic AI equivalent |
|---|---|
| `_headers()` sending `HTTP-Referer` / `X-Title` | `OpenRouterProvider(api_key=, app_url=, app_title=)` |
| the candidate walk in `complete()` / `stream()` | `FallbackModel(m1, m2, …, fallback_on=…)` |
| `_check_quota()` per-account hourly cap | `UsageLimits(request_limit=, tool_calls_limit=)` per run |
| `ChatUnavailable(status=, retry_after=)` | stays — it is the HTTP contract, kept at the boundary |
| `_bench()` / `_benched()` cooldowns | stays — Pydantic AI has no equivalent, and it is the thing that absorbs free-tier rotation |

Install is `pydantic-ai-slim[openrouter]`, not the full `pydantic-ai` meta-package — the slim
build pulls only the OpenRouter provider.

---

## Architecture

```
routes/chat.py  ──►  chat_service.answer()/stream_answer()
                          │
                          ├─ gate: does this need the loop?     ◄── Phase 2
                          │     └─ no  ─► today's single-shot path (unchanged)
                          │
                          └─ yes ─► agent/runner.py
                                        │   Agent(FallbackModel, deps_type=AgentDeps,
                                        │         output_type=PromptedOutput|tool, tools=[…])
                                        │
                                        ├─ agent/models.py   ◄─ llm_client.available_models()
                                        ├─ agent/deps.py     ◄─ read-only DuckDB conn + page
                                        ├─ agent/tools/*.py  ◄─ insights/reads/brief/series
                                        ├─ agent/cache.py    (per-run + per-day memoisation)
                                        └─ agent/trace.py    (JSONL trace, feeds Phase 6)
```

### New package: `thaalam/agent/`

| File | Purpose |
|---|---|
| `__init__.py` | Public surface only: `run_agent()`, `stream_agent()`, `AgentUnavailable`. Nothing else imported at module scope, so a no-key install never touches Pydantic AI. |
| `models.py` | Turns `llm_client.available_models()` into a `FallbackModel`. Owns tool-capability filtering and the `PromptedOutput` decision. |
| `deps.py` | `AgentDeps` frozen dataclass: the read-only `duckdb.DuckDBPyConnection`, page key, read id, range_days, a per-run cache, and the trace handle. This is what `RunContext[AgentDeps]` carries. |
| `tools/` | One module per domain area (`analytics.py`, `reads.py`, `series.py`, `compare.py`). Each function is a thin typed wrapper over an existing service. |
| `runner.py` | Builds the `Agent`, sets `UsageLimits`, runs it, maps every failure onto `ChatUnavailable`. Both buffered and streamed entry points. |
| `gate.py` | The cheap routing step that decides single-shot vs agent loop. |
| `cache.py` | Tool-result memoisation. Per-run dict + a process-wide TTL cache keyed on `(tool, args, latest_data_date)`. |
| `trace.py` | Appends one JSONL line per run to `DATA_DIR/traces/`. Becomes the eval harness's input in Phase 6. |
| `schemas.py` | The typed output: `GroundedAnswer` (text, `citations: list[Citation]`, `confidence`, `missing: list[str]`). |

Nothing in `thaalam/services/` is deleted. `chat_context.build_context()` stays and keeps
doing what it does well — it becomes the agent's *opening context*, not its only context.

---

## 1. Models: the free roster becomes a `FallbackModel`

`llm_client.available_models()` already returns free slugs ranked by
`(_preference_rank, -context_length)`. Two changes:

**a. Capture `supported_parameters`.** `GET /models` returns a `supported_parameters` list
per model containing entries like `"tools"` and `"response_format"`. `_rank_models()`
currently discards everything but the slug. Widen its return to carry capability flags —
a `FreeModel` dataclass (`slug`, `context_length`, `supports_tools`, `supports_response_format`)
— and keep a slug-only `available_models()` wrapper so `complete()` and `stream()` are
untouched. Add a new `available_models_detailed()` for the agent path.

**b. `agent/models.py` builds the chain:**

```
build_model() ->
  slugs = llm_client.available_models_detailed()          # already ranked, already benched
  tool_capable = [m for m in slugs if m.supports_tools]
  chain = [OpenRouterModel(m.slug, provider=OpenRouterProvider(
               api_key=…, app_url=…, app_title=…),
               settings=ModelSettings(temperature=0.2, max_tokens=…))
           for m in (tool_capable or slugs)[:3]]
  return FallbackModel(*chain, fallback_on=(ModelAPIError, …)), bool(tool_capable)
```

The second return value picks the output mode:

- **tool-capable roster** → default tool output for `GroundedAnswer`, and real tool calling.
- **no tool-capable model free right now** → `PromptedOutput(GroundedAnswer)`, which works on
  every model, and the gate biases hard toward single-shot (a model that cannot tool-call
  cannot usefully loop).

`OPENROUTER_MODEL` pinning still wins, and a new `OPENROUTER_AGENT_MODEL` may pin the agent
path separately — `openrouter/free` (OpenRouter's free router, which itself filters for
tool-calling) is a sensible value to document.

**Cooldowns stay in `llm_client`.** `FallbackModel`'s `fallback_on` handler calls
`llm_client._bench(slug)` on 400/404/429 so a slug retired during an agent run is also
retired for the single-shot path. One rotation state for the whole app.

---

## 2. The tool surface

Every tool takes `RunContext[AgentDeps]` and reads `ctx.deps.con`. All are **deterministic
Python over DuckDB** — none costs a model turn, which is the whole point on a 50-req/day
budget. Each returns a small typed Pydantic model, never a DataFrame.

| Tool | Wraps | Returns | Why it earns a slot |
|---|---|---|---|
| `get_today()` | `brief_service.build_snapshot()` | `SnapshotOut` | The one call every answer starts from. |
| `get_insight(section)` | `insights_service.build_insights()` → one key | `InsightOut` | Lets the model fetch only the section it needs instead of all 11 travelling on every prompt. Validated against the literal section keys (`hrv`, `rhr`, `training_load`, `strain_recovery_lag`, `sleep_recovery`, `sleep_debt`, `recovery_zones`, `weekday_patterns`, `training_readiness`). |
| `list_reads(flagged_only)` | `reads_service.get_reads_payload()` | `list[ReadSummary]` | The dashboard's own findings, cheap to list. |
| `explain_read(read_id)` | `reads_service.get_read_dive_payload()` | `ReadDive` | The drill-down. `read_id` constrained to `READ_ORDER` (`restorative_yield`, `stage_dependency`, `hyperarousal`, `timing_regularity`, `strain_sensitivity`, `cardiac_efficiency`, `adaptation_window`, `runway`, `circadian_phase`, `habit_persistence`, `timing_contribution`). |
| `get_series(metric, days)` | `repositories/queries.load_recovery/load_cycles/load_sleep/load_workouts` | `SeriesOut` (dates + values, **downsampled**) | This is the capability that does not exist today. Unlocks every "how has X moved" question. |
| `compare_windows(metric, window_a, window_b)` | new, over `queries.*` | `ComparisonOut` (mean, delta, n, whether the gap clears noise) | Turns "is this week worse?" into arithmetic instead of model estimation — the single biggest hallucination class in the current design. |
| `get_vitality()` | `vitality_score.build_vitality_payload()` | `VitalityOut` | Component breakdown, already computed. |
| `get_runway()` | `db.get_derived_runway()` ∥ `runway_service.compute_runway()` | `RunwayOut` | Prefers the stored derived row; computes only on a miss. |
| `get_headline_scores()` | `headline_scores.compute_headline(con, *, now=, user_id=)` | `HeadlineOut` | The three scores the Today tab leads with. |
| `explain_preset(key)` | `brief_service.answer_explainer(snapshot, key)` | `str` | The app's **four** rule-written answers — `recovery_drivers`, `training_load`, `sleep_debt`, `push_or_rest` — in the app's own voice. See the zero-call path below; this is the highest-value tool in the list. |
| `get_data_coverage()` | `db.get_sync_state()` + earliest/latest rows | `CoverageOut` | Lets the model *know* it has 9 days of history and say so, rather than answering a 90-day question from 9 days. |

**The zero-model-call path.** `brief_service.EXPLAINERS` already maps four keys to complete,
rule-written answers to the four most common dock questions — and those four are almost
verbatim the starter prompts `chat_context._SUGGESTIONS` puts in front of the user
("Should I push hard today or take it easy?", "How is my sleep debt?"). A click on a
suggestion chip is therefore answerable by `answer_explainer()` with **no model call at all**.
The gate should match these first, before deciding single-shot vs agent. On a 50-request day
this is likely the largest single budget saving available, and it costs one dictionary lookup.

**`ModelRetry` for grounding.** A tool asked for a metric with no data raises `ModelRetry`
with a message naming what is missing and what would produce it — the model corrects instead
of inventing. This is rule 2 of `SYSTEM_PROMPT` made mechanical.

**No write tools, ever.** `deps.con` is the read-only connection from
`get_optional_readonly_connection`. No tool triggers a sync, a recompute, or any mutation.

---

## 3. Budget: the mechanism

A naive agent loop turns one question into 3–6 model calls. On 50 free requests a day shared
across a household, that is the feature killing itself. Four mechanisms, in order:

**a. The gate (`agent/gate.py`) — zero model calls.** Three-way, checked in order:

1. **Preset match → zero requests.** The question matches one of the four
   `brief_service.EXPLAINERS` questions (exactly, as a clicked suggestion chip, or by close
   normalised match) → return `answer_explainer()` directly. No model involved.
2. **Simple → one request.** Deterministic heuristics over the text and page: it names no
   time window, asks for no comparison, and stays inside the current page's
   `_PAGE_SECTIONS` → today's single-shot path, unchanged. Expect most remaining dock
   questions here, because `build_context` already contains their answer.
3. **Complex → the agent loop.** It names a time window, asks for a comparison, reaches for a
   metric off the current page, or follows up on a prior turn.

> An LLM-based router is a *later* refinement, and only if the heuristic gate proves wrong on
> traced questions. It would cost a model call, which is the thing being conserved.

**b. `UsageLimits` per run.** `UsageLimits(request_limit=4, tool_calls_limit=8,
total_tokens_limit=…)`. `request_limit` caps model turns — the budget-relevant number, since
tool calls are free Python. Values become settings: `AGENT_MAX_TURNS`, `AGENT_MAX_TOOL_CALLS`.

**c. Tool-result cache (`agent/cache.py`).** Keyed `(tool_name, sorted_args, latest_data_date)`.
The data date is the invalidation key — health data changes once a day, so a cached
`get_insight("hrv")` is valid until the next sync. Per-run dict plus a process-wide TTL dict
in the same module-level style as `llm_client._cache`. Costs nothing and removes the
repeated-lookup failure mode entirely.

**d. The fallback ladder**, walked top-down when the budget bites:

1. Agent loop with tools (the target path).
2. Budget low (`chat_requests_per_hour` nearly spent, or every slug benched) → single-shot
   grounded path, with a `degraded: true` flag on the response so the dock can say so.
3. Budget spent, but the question matches a preset → `answer_explainer()`, which needs no
   model at all. The assistant still answers the four commonest questions with the allowance
   at zero — a strictly better floor than today's behaviour.
4. `ChatUnavailable(429)` from `llm_client` → today's "try again shortly", unchanged.
5. No key → assistant off, unchanged.

A new `AGENT_ENABLED` setting (default `true` when `chat_configured`) makes step 2 the
permanent behaviour for anyone who wants it.

---

## 4. Streaming: keeping the commitment point

The existing SSE contract is `meta` → `start` → `delta`… → `done`, plus an `error` frame
(`routes/chat.py:200-240`, consumed by the `switch` in `frontend/src/api.ts:352`). Its
load-bearing property is that **everything knowable before the first token is an HTTP
status**. An agent loop threatens that: tool calls happen *between* model turns, so the first
token can now be several seconds and several steps in.

The design keeps the commitment point where it is:

- `agent.run_stream()` is used only for the **final** answer turn. The planning and
  tool-calling turns run buffered, before anything reaches the browser. A failure during them
  is still an HTTP status.
- One new SSE event kind, **`step`**, emitted as tools execute: `{tool, summary}` — e.g.
  `{"tool": "compare_windows", "summary": "comparing last 7 days to the 28 before"}`. The dock
  renders these as a live "working" line above the answer. This is a *progress* signal, not
  content: the answer still begins at `start`.
- `meta` gains `mode: "agent" | "single" | "rules"` (the third being the zero-call preset path)
  and `degraded: bool`, so the UI can be honest about which path served the answer.
- `frontend/src/api.ts` and `ChatProvider.tsx` learn `step`. **Adding an event kind is
  already safe**: the `switch` in `api.ts:352` has no `default` clause, so an older frontend
  against a newer backend silently ignores `step` and behaves exactly as it does today. No
  lockstep deploy required.

Files touched: `thaalam/api/routes/chat.py` (`_frame` call sites), `frontend/src/api.ts`,
`frontend/src/chat/ChatProvider.tsx`, `frontend/src/components/chat/ChatDock.tsx`.

---

## 5. Phasing

Each phase is independently shippable and leaves the app working.

### Phase 1 — Runtime foundation *(no user-visible change)*
- Add `pydantic-ai-slim[openrouter]` to `pyproject.toml`.
- `thaalam/agent/{__init__,models,deps,schemas,cache,trace}.py`.
- Widen `_rank_models()` to carry `supported_parameters`; add `available_models_detailed()`.
- Three tools only: `get_today`, `get_insight`, `explain_preset`.
- `runner.py` runs the agent behind `AGENT_ENABLED=false` (off by default).
- **Testable:** fake model + fake `_Session`, no network. The single-shot path is untouched.

### Phase 2 — The loop goes live *(feature: multi-step answers)*
- `gate.py` (all three branches, preset-match first) + the fallback ladder + `UsageLimits`.
- Remaining tools: `list_reads`, `explain_read`, `get_vitality`, `get_runway`,
  `get_headline_scores`, `get_data_coverage`.
- `AGENT_ENABLED=true` by default when a key is configured.
- **Unlocks:** "why is my recovery down *and* is my training the reason?" — questions needing
  two sections the current `_PAGE_SECTIONS` map would not have put together. Also the
  zero-call preset path, which makes the four commonest questions instant and free.

### Phase 3 — Series and comparison *(feature: time-range questions)*
- `get_series` + `compare_windows`, with downsampling so a 90-day series is a handful of
  tokens.
- `GroundedAnswer.citations` populated — every figure carries the tool and date range it came
  from, rendered in the dock under the answer next to the existing `grounded_on` chips.
- **Unlocks:** "how has my HRV moved this month?", "is this week actually worse than last?",
  "when did my sleep debt start?" — none of which are answerable today.

### Phase 4 — Streaming + progress UI
- `step` events, `mode`/`degraded` in `meta`, the dock's working line.
- **Unlocks:** an agent answer that takes 8 seconds stops looking like a hang.

### Phase 5 — Memory *(feature: follow-ups and continuity)*
- Persist conversations to the **SQLite** auth DB (`data/thaalam_auth.db`) — never DuckDB,
  which allows one writer and is already held by sync. New tables: `chat_conversation`,
  `chat_message`.
- Per-account, scoped by session, deleted with the account.
- Compaction: summarise turns beyond `chat_history_messages` into a running summary rather
  than dropping them, which is what `_prepare()` does today.
- **Unlocks:** "and what about last week?" resolving against the previous question; the dock
  surviving a page reload.
- *Privacy note:* this stores questions and answers at rest for the first time. It needs an
  explicit opt-out setting (`CHAT_HISTORY_PERSIST`), a README line, and inclusion in the
  existing account-deletion path.

### Phase 6 — Evals and tracing *(the scoreboard, deliberately last per the chosen order)*
- `tests/eval/golden.jsonl`: 40–60 questions over a fixture DuckDB with known answers.
- Scorers that need no LLM: does the answer contain the right figure; did it cite the right
  tool; did it refuse when data was absent; how many model turns did it take.
- An LLM-as-judge tier, opt-in and off in CI, for tone and helpfulness.
- `trace.py`'s JSONL is the input; `uv run python -m thaalam.agent.eval` is the entry point.
- Add `.github/workflows/ci.yml` (the repo has none) running `uv run pytest` — the
  deterministic scorers gate, the judge does not.

### Phase 7 — Features the loop makes cheap
Pick from, in rough value order:
- **Proactive nightly brief.** `nightly_job.py` already runs at 04:00; one agent run a day
  produces a written brief over the deterministic `compose_brief()` rules. One request, huge
  perceived value.
- **"What-if" questions.** "If I sleep 8 hours tonight, what happens to my runway?" —
  `runway_service` already projects; the tool takes a hypothetical input.
- **Weekly review.** One agent run a week over `compare_windows`.

---

## 6. Testing

**Network-free, matching the existing convention** (`tests/test_llm_client.py` and
`test_llm_stream.py` already build `_Response`/`_Session` stubs; `tests/conftest.py` has the
`tmp_db` fixture).

- `tests/test_agent_tools.py` — every tool against `tmp_db`, no model at all. These are plain
  data tests and should be the bulk of the coverage.
- `tests/test_agent_models.py` — `FallbackModel` construction from a stub roster: tool-capable
  present, none tool-capable, empty, all benched.
- `tests/test_agent_gate.py` — the three-way classification, table-driven. Must include: every
  `_SUGGESTIONS` chip that maps to an `EXPLAINERS` key routes to `rules` and calls no model
  at all (assert with a model stub that raises if invoked).
- `tests/test_agent_runner.py` — Pydantic AI's `TestModel`/`FunctionModel` to drive tool calls
  deterministically with no network.
- `tests/test_agent_budget.py` — `UsageLimits` enforced; the ladder degrades in the right
  order.
- `tests/test_chat_stream_routes.py` — extended for `step` events and the `mode`/`degraded`
  fields.

Add `[tool.pytest.ini_options]` to `pyproject.toml` (there is none today) to mark the eval
tier so `uv run pytest` stays fast.

---

## 7. Risks

| Risk | Mitigation |
|---|---|
| **Free models are bad at tool-calling.** The most likely failure. | Filter on `supported_parameters` containing `"tools"`; `PromptedOutput` when none qualify; the gate keeps most traffic single-shot; document `OPENROUTER_AGENT_MODEL=openrouter/free`. Phase 1 ships behind a flag precisely so this can be measured before it is default. |
| **The loop burns the daily budget.** | The gate is the primary defence (most questions never enter the loop), then `UsageLimits(request_limit=4)`, then the cache, then the ladder back to single-shot. Trace every run's turn count from Phase 1 so the real multiplier is known, not guessed. |
| **Latency regression.** Today's answer starts streaming in ~1s; an agent answer may take 5–10s. | Tools are local DuckDB reads (milliseconds), so the cost is model turns, capped at 4. `step` events (Phase 4) make the wait legible. The gate means fast questions stay fast. |
| **Dependency weight.** | `pydantic-ai-slim[openrouter]` only. Verify the added tree with `uv tree` before merging Phase 1 and record the count; if it is not modest, the in-house-only path is still open because `llm_client` was never removed. |
| **Single worker.** | All new state is module-level in-process (matching `_cache`, `_cooldowns`, `_history`) or SQLite. Nothing new touches DuckDB for writes. |
| **Prompt injection via tool output.** New surface: tool results now re-enter the prompt. | Tool outputs are typed Pydantic models rendered by our code, never raw strings from user-controllable fields. The client still sends identifiers only; the `system` role stays server-owned. |
| **Privacy regression.** | Phases 1–4 change nothing about what leaves the machine — the same grounding figures, no identity. Phase 5 is the one that stores data at rest, and carries its own opt-out and README change. `thaalam/agent/` must not import Pydantic AI at module scope, so a no-key install is unaffected. |
| **The agent answers worse but sounds better.** | This is the real reason Phase 6 exists. Until it lands, `AGENT_ENABLED` is the escape hatch and traces accumulate for the golden set. |

---

## 8. Verification

**Per phase, locally:**
```bash
uv sync
uv run pytest                                  # network-free, must stay green throughout
uv run run_api.py                              # API on 8001
cd frontend && npm run build && npm run dev    # tsc --noEmit + Vite on 3001
```

**End to end, with a real key** (`OPENROUTER_API_KEY` set):
1. Open the dock on the Recovery page and click the *"Why is my recovery where it is today?"*
   suggestion → expect `mode: "rules"` in `meta` and **no outbound request at all** (confirm
   in the log: no `Chat streaming on page=…` line). This is the preset path.
2. Ask *"how does my sleep compare to my strain this month?"* → expect `mode: "single"` or
   `"agent"` but never `"rules"`, and a real answer either way.
3. Ask *"is this week's HRV worse than the three weeks before?"* → expect `mode: "agent"`,
   `step` events naming `compare_windows`, and citations carrying both date ranges.
4. Ask about a metric with no synced history → expect a refusal naming the missing metric, not
   an invented number (`ModelRetry` path).
5. Unset the key, restart → `/api/chat/status` reports `enabled: false`, the dock hides,
   no outbound request is made, and nothing imports Pydantic AI.
6. Spend the hourly allowance → expect the ladder: agent → single-shot `degraded: true` →
   preset answers still working at zero budget → `429` with `retry_after` for everything else.

**Budget check:** after a day of use, `agent/trace.py`'s JSONL gives requests-per-question.
If the median is above ~1.5, the gate is too permissive — tighten it before widening tools.

---

## References

- [LangGraph vs LangChain: production architecture 2026](https://dev.to/dr_hernani_costa/langgraph-vs-langchain-production-ai-architecture-2026-2ahm) — why a graph framework is overkill here
- [Pydantic AI — OpenRouter](https://github.com/pydantic/pydantic-ai/blob/main/docs/models/openrouter.md) · [FallbackModel](https://github.com/pydantic/pydantic-ai/blob/main/docs/models/overview.md) · [pydantic_ai.usage](https://pydantic.dev/docs/ai/api/pydantic-ai/usage/)
- [Python agent library comparison: Pydantic AI vs Instructor vs smolagents](https://jangwook.net/en/blog/en/python-ai-agent-library-comparison-2026/) — latency figures behind the framework choice
- [OpenRouter Free Models Router](https://openrouter.ai/docs/guides/routing/routers/free-router) · [Structured Outputs](https://openrouter.ai/docs/guides/features/structured-outputs)
- [LLM agent evaluation metrics 2026](https://www.confident-ai.com/blog/llm-agent-evaluation-complete-guide) — trajectory and tool-call accuracy, for Phase 6
- [Automated optimization for agents: 5 axes](https://futureagi.com/blog/automated-optimization-for-agent-2026/) — prompt, tool descriptions, retrieval, few-shot, model
- [Failure Makes the Agent Stronger: structured reflection for tool interactions](https://arxiv.org/pdf/2509.18847) — the `ModelRetry` pattern
- [Reflective Prompt Evolution with GEPA](https://dspy.ai/tutorials/gepa_ai_program/) — an option for Phase 6+ once a golden set exists
