import { AlertTriangle, Download, RefreshCw, Table2 } from "lucide-react";
import { Suspense, lazy, useEffect, useMemo, useState } from "react";
import { get, post } from "../lib/api";
import { downloadFile } from "../lib/native";
import { actions, useStore } from "../lib/store";
import { LEVELS, ProviderDot, fmtAgo, fmtTokens, fmtUsd, modelLabel, modelName, providerLabel, providerModels, providerRank, tiersOf, useModelCatalog } from "../components/ui";
import { CustomRange, customBounds, defaultCustom } from "../components/DateRange";

// Recharts is a separate chunk: the page renders its numbers at once and the charts fill in.
const charts = () => import("../components/UsageCharts");
const TokensChart = lazy(() => charts().then((m) => ({ default: m.TokensChart })));
const CostChart = lazy(() => charts().then((m) => ({ default: m.CostChart })));
const ElevenChart = lazy(() => charts().then((m) => ({ default: m.ElevenChart })));
const ChartSlot = ({ children }: { children: React.ReactNode }) => (
  <Suspense fallback={<div className="h-full rounded bg-sunken animate-pulse" aria-label="Loading chart" />}>{children}</Suspense>
);

const CUSTOM = "Custom…";
const RANGES: Record<string, number | null> = { "24h": 86400, "7 days": 7 * 86400, "30 days": 30 * 86400, "All time": null, [CUSTOM]: null };
// "Output" is visible output only; reasoning has its own series. Providers bill both as output,
// so output + reasoning is the billed output count (the backend splits them the same way).
const SERIES = [
  { key: "input", label: "Input", color: "var(--s1)" },
  { key: "output", label: "Output", color: "var(--s2)", hint: "Visible output, excluding reasoning" },
  { key: "cached", label: "Cached", color: "var(--s3)" },
  { key: "reasoning", label: "Reasoning (billed as output)", color: "var(--s4)", hint: "Thinking tokens, billed at the output rate" },
];
// Warnings get a triangle instead of a dot, so they never read as a provider colour.
const STATUS: Record<string, { label: string; color: string; warn?: boolean }> = {
  online: { label: "Online", color: "var(--ok)" },
  auth_failed: { label: "Auth failed", color: "var(--bad)" },
  unreachable: { label: "Unreachable", color: "var(--warn)", warn: true },
  no_key: { label: "No key", color: "var(--faint)" },
  unavailable: { label: "Not in model list", color: "var(--warn)", warn: true },
  unknown: { label: "Not checked", color: "var(--faint)" },
};

function StatusBadge({ status, title }: { status: string; title?: string }) {
  const s = STATUS[status] ?? STATUS.unknown;
  return (
    <span className="inline-flex items-center gap-1.5 text-[12.5px]" title={title}>
      {s.warn ? <AlertTriangle size={12} style={{ color: s.color }} aria-hidden />
        : <span className="size-2 rounded-full" style={{ background: s.color }} aria-hidden />}
      {s.label}
    </span>
  );
}

export function UsagePage() {
  useModelCatalog();
  const sessions = useStore((s) => s.sessions);
  const [range, setRange] = useState("7 days");
  const [custom, setCustom] = useState(defaultCustom);
  const [f, setF] = useState({ session_id: "", provider: "", model: "", role: "" });
  const [status, setStatus] = useState<any>(null);
  const [models, setModels] = useState<any[]>([]);
  const [eleven, setEleven] = useState<any>(null);
  const [cmp, setCmp] = useState<any[]>([]);
  const [savings, setSavings] = useState<any>(null);
  const [refreshing, setRefreshing] = useState(false);

  const qs = useMemo(() => {
    const p = new URLSearchParams();
    const r = RANGES[range];
    if (range === CUSTOM) {
      const b = customBounds(custom);
      if (b.since != null) p.set("since", String(b.since));
      if (b.until != null) p.set("until", String(b.until));
    } else if (r) p.set("since", String(Date.now() / 1000 - r));
    Object.entries(f).forEach(([k, v]) => v && p.set(k, v));
    return p.toString();
  }, [range, custom, f]);

  const load = async () => {
    const [st, ms, el, c, sv] = await Promise.all([
      get("/status"), get(`/usage/models?${qs}`), get(`/usage/elevenlabs?${qs}`), get(`/usage/comparison?${qs}`), get(`/usage/savings?${qs}`),
    ]);
    setStatus(st); setModels(ms); setEleven(el); setCmp(c); setSavings(sv);
  };
  useEffect(() => { load().catch((e) => actions.toast(e.message, "error")); }, [qs]);
  useEffect(() => { charts().catch(() => {}); }, []); // fetch the chart chunk alongside the data
  useEffect(() => actions.onEvent((e) => { if (e.type === "status.updated") setStatus(e.data); }), []);
  // The backend re-reads the ElevenLabs subscription a few seconds after each generation. Patch that
  // profile's quota in place (the card may show any profile), then refetch for the new totals.
  useEffect(() => actions.onEvent((e) => {
    if (e.type !== "elevenlabs.quota") return;
    const { profile, subscription, checked_at } = e.data ?? {};
    setEleven((cur: any) => {
      if (!cur) return cur;
      const patch = (x: any) => x.profile === profile ? { ...x, quota: subscription, quota_checked_at: checked_at } : x;
      const top = cur.profile === profile ? { quota: subscription, quota_checked_at: checked_at } : {};
      return { ...cur, ...top, quotas: (cur.quotas ?? []).map(patch) };
    });
    get(`/usage/elevenlabs?${qs}`).then(setEleven).catch(() => {});
  }), [qs]);

  const refresh = async () => {
    setRefreshing(true);
    try { setStatus(await post("/status/refresh")); } finally { setRefreshing(false); }
  };
  const exportCsv = () => downloadFile(`/usage/export.csv?${qs}`, "gamedevworkstation-usage.csv");
  const allModels = Object.keys(status?.models ?? {});
  const modelsOf = (p: string) => allModels.filter((m) => status.models[m].provider === p);

  return (
    <div className="h-full overflow-y-auto scroll-thin">
      <div className="max-w-[1180px] mx-auto px-6 py-5 space-y-5">
        <div className="flex items-center gap-3">
          <h1 className="text-lg font-semibold">My usage</h1>
          <button className="btn ml-auto" onClick={exportCsv}><Download size={14} /> Export CSV</button>
        </div>

        <section aria-label="Provider status" className="rounded-md border border-line surface">
          <div className="flex items-center px-3 py-2 border-b border-line">
            <span className="font-medium">Provider status</span>
            <span className="ml-3 text-[12px] text-faint">Checks run at launch and every 15 minutes.</span>
            <button className="btn ml-auto" onClick={refresh} disabled={refreshing}><RefreshCw size={13} className={refreshing ? "animate-spin" : ""} /> Refresh</button>
          </div>
          <div className="grid grid-cols-[repeat(auto-fit,minmax(220px,1fr))]">
            {[...(status?.providers ?? [])].sort((a: any, b: any) => providerRank(a.provider) - providerRank(b.provider)).map((p: any) => (
              <div key={p.provider + p.profile} className="px-3 py-2.5 min-w-0 border-r border-line last:border-r-0">
                <div className="flex items-center gap-2">
                  <ProviderDot provider={p.provider} />
                  <span className="font-medium">{providerLabel(p.provider)}</span>
                  {p.profile !== "default" && <span className="chip">{p.profile}</span>}
                </div>
                <div className="mt-1"><StatusBadge status={p.status} /></div>
                {providerModels(p.provider).length > 0 && (
                  <div className="text-[12px] text-muted max-w-[320px]" title={providerModels(p.provider).map((m) => m.id).join(", ")}>{providerModels(p.provider).map((m) => m.name).join(", ")}</div>
                )}
                <div className="text-[12px] text-faint">checked {fmtAgo(p.checked_at)}</div>
                {p.error && <div className="text-[12px] text-muted mt-0.5 max-w-[320px] line-clamp-2" title={p.error}>{p.error}</div>}
              </div>
            ))}
            {!status?.providers?.length && <div className="col-span-full px-3 py-3 text-muted text-[13px]">No checks yet. Press Refresh.</div>}
          </div>
        </section>

        <div className="flex flex-wrap items-center gap-2 text-[13px]" role="group" aria-label="Filters">
          <div className="inline-flex rounded border border-line overflow-hidden">
            {Object.keys(RANGES).map((r) => (
              <button key={r} className={`px-2.5 py-1 ${range === r ? "bg-sunken font-medium" : "hover:bg-sunken"}`} aria-pressed={range === r} onClick={() => setRange(r)}>{r}</button>
            ))}
          </div>
          {range === CUSTOM && <CustomRange value={custom} onChange={setCustom} />}
          <select className="input w-[220px]" value={f.session_id} onChange={(e) => setF({ ...f, session_id: e.target.value })} aria-label="Session">
            <option value="">All sessions</option>
            {sessions.filter((s) => !s.deleted).map((s) => <option key={s.id} value={s.id}>{s.title}</option>)}
          </select>
          <select className="input w-[150px]" value={f.provider} onChange={(e) => setF({ ...f, provider: e.target.value })} aria-label="Provider">
            <option value="">All providers</option>{["anthropic", "openai", "elevenlabs"].map((p) => <option key={p} value={p}>{providerLabel(p)}</option>)}
          </select>
          <select className="input w-[220px]" value={f.model} onChange={(e) => setF({ ...f, model: e.target.value })} aria-label="Model">
            <option value="">All models</option>
            {["anthropic", "openai"].map((p) => modelsOf(p).length > 0 && (
              <optgroup key={p} label={providerLabel(p)}>{modelsOf(p).map((m) => <option key={m} value={m}>{modelLabel(m)}</option>)}</optgroup>
            ))}
          </select>
          <select className="input w-[180px]" value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })} aria-label="Role">
            <option value="">All roles</option><option value="main">Main agent</option><option value="subagent">Subagents</option>
            <option value="other" title="Compacting, the Skills assistant, web search and tools">Other</option>
          </select>
        </div>

        {savings && savings.actual > 0 && (
          <section className="rounded-md border border-line surface px-4 py-3 flex flex-wrap items-baseline gap-x-8 gap-y-1">
            <div><div className="label">Spent</div><div className="text-xl font-semibold">{fmtUsd(savings.actual)}</div></div>
            <div><div className="label">If {modelLabel(savings.orchestrator_model)} had done it all</div><div className="text-xl">{fmtUsd(savings.estimated_without_delegation)}</div></div>
            <div><div className="label">Delegation saved</div><div className="text-xl" style={{ color: savings.saved >= 0 ? "var(--ok)" : "var(--bad)" }}>{fmtUsd(savings.saved)}</div></div>
            <div className="text-[12px] text-faint basis-full">Estimate: subagent tokens priced at the orchestrator's rates. A larger model at its own effort usually thinks more, so the real difference tends to be bigger.{savings.other_actual > 0 ? ` Compacting, the Skills assistant and tool calls (${fmtUsd(savings.other_actual)}) count the same on both sides.` : ""}</div>
          </section>
        )}

        <div className="grid gap-4 grid-cols-[repeat(auto-fill,minmax(min(100%,460px),1fr))]">
          {models.map((m) => <ModelCard key={m.model} m={m} />)}
          {eleven && (eleven.total_characters > 0 || eleven.quota) && <ElevenCard e={eleven} />}
        </div>
        {!models.length && <div className="text-muted text-[13px]">No model usage in this range yet.</div>}

        {cmp.length > 0 && (
          <section className="rounded-md border border-line surface">
            <div className="px-3 py-2 border-b border-line font-medium">Comparison</div>
            <div className="overflow-x-auto">
              <table className="w-full text-[13px]">
                <thead className="text-muted text-left"><tr className="border-b border-line">
                  <th className="px-3 py-1.5 font-normal">Model</th><th className="px-3 font-normal text-right">Cost</th><th className="px-3 font-normal text-right">Tokens</th>
                  <th className="px-3 font-normal text-right">Requests</th><th className="px-3 font-normal text-right">Tasks</th><th className="px-3 font-normal text-right">Success</th>
                  <th className="px-3 font-normal">Avg cost per task kind</th>
                </tr></thead>
                <tbody>
                  {cmp.map((c) => (
                    <tr key={c.model} className="border-b border-line last:border-0 align-top">
                      <td className="px-3 py-1.5"><span className="inline-flex items-center gap-1.5" title={c.model}><ProviderDot model={c.model} />{modelLabel(c.model)}</span></td>
                      <td className="px-3 text-right tabular-nums">{fmtUsd(c.cost)}</td>
                      <td className="px-3 text-right tabular-nums" title={c.provider === "elevenlabs" ? "ElevenLabs bills characters and credits, not tokens" : undefined}>{c.provider === "elevenlabs" ? elevenAmount(c) : fmtTokens(c.tokens)}</td>
                      <td className="px-3 text-right tabular-nums">{c.requests}</td>
                      <td className="px-3 text-right tabular-nums">{c.tasks}</td>
                      <td className="px-3 text-right tabular-nums">{c.success_rate == null ? "—" : `${Math.round(c.success_rate * 100)}%`}</td>
                      <td className="px-3 text-muted">{Object.entries(c.by_job_type).map(([k, v]: any) => `${k} ${fmtUsd(v.avg_cost)}`).join(", ") || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

/** "1.2k chars" or "600 credits" for ElevenLabs rows, which have no tokens. */
function elevenAmount(x: { characters?: number; credits?: number }): string {
  return x.characters ? `${fmtTokens(x.characters)} chars` : `${fmtTokens(Math.round(x.credits ?? 0))} credits`;
}

function Stat({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return <div className="min-w-0" title={hint}><div className="label truncate">{label}</div><div className="tabular-nums whitespace-nowrap">{value}</div></div>;
}

function ModelCard({ m }: { m: any }) {
  const [table, setTable] = useState(false);
  const efforts = Object.entries(m.effort as Record<string, number>).sort(([a], [b]) => LEVELS.indexOf(a) - LEVELS.indexOf(b));
  const effortTotal = efforts.reduce((a, [, v]) => a + v, 0);
  return (
    <section className="rounded-md border border-line surface flex flex-col" aria-label={`${m.display_name ?? modelName(m.model)} usage`}>
      <div className="flex items-center gap-2 px-3 py-2 border-b border-line">
        <ProviderDot model={m.model} />
        <span className="font-medium" title={m.model}>{m.display_name ?? modelName(m.model)}</span>
        {(tiersOf(m.model).length ? tiersOf(m.model) : m.tier ? [m.tier] : []).map((t: string) => <span key={t} className="chip">{t}</span>)}
        <span className="ml-auto"><StatusBadge status={m.status.status} title={m.status.reason ?? undefined} /></span>
      </div>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(112px,1fr))] gap-x-3 gap-y-2 px-3 pt-2.5 text-[13px]">
        <Stat label="Cost" value={fmtUsd(m.cost)} />
        <Stat label="Requests" value={m.requests} />
        <Stat label="Latency p50/p95" hint="Median (p50) / 95th percentile (p95) response time" value={m.latency_p50 == null ? "—" : `${(m.latency_p50 / 1000).toFixed(1)}s / ${(m.latency_p95 / 1000).toFixed(1)}s`} />
        <Stat label="Errors / limited" hint="Share of requests that failed / were rate-limited" value={`${Math.round(m.error_rate * 100)}% / ${Math.round(m.rate_limit_rate * 100)}%`} />
        <Stat label="Cache hits" hint="Input tokens read from the prompt cache" value={`${Math.round(m.cache_hit_rate * 100)}%`} />
        <Stat label="Context fill" hint="Average share of the context window used per request" value={m.avg_context_fill == null ? "—" : `${(m.avg_context_fill * 100).toFixed(1)}%`} />
        <Stat label="Main agent" hint="Share of requests made by the main agent (the rest are subagents and other roles)" value={`${Math.round(m.share_main * 100)}%`} />
        <Stat label="Headroom" hint="Rate-limit headroom left, from the provider's last response headers" value={m.rate_limits?.tokens_remaining != null ? `${fmtTokens(m.rate_limits.tokens_remaining)} tok` : m.rate_limits?.requests_remaining != null ? `${m.rate_limits.requests_remaining} req` : "—"} />
      </div>

      <div className="px-3 pt-3 flex items-center gap-3 text-[12px] flex-wrap">
        <span className="font-medium text-[13px]">Tokens</span>
        {SERIES.map((s) => (
          <span key={s.key} className="inline-flex items-center gap-1 text-muted" title={s.hint}>
            <span className="size-2.5 rounded-sm" style={{ background: s.color }} aria-hidden />{s.label} <span className="text-text tabular-nums">{fmtTokens(m.tokens[s.key])}</span>
          </span>
        ))}
        <button className="btn btn-ghost ml-auto px-1.5 py-0.5" aria-pressed={table} onClick={() => setTable(!table)} title="Show as table"><Table2 size={13} /></button>
      </div>
      {table ? (
        <div className="px-3 py-2 overflow-x-auto max-h-56">
          <table className="w-full text-[12px] tabular-nums">
            <thead className="text-muted"><tr><th className="text-left font-normal">Day</th>{SERIES.map((s) => <th key={s.key} className="text-right font-normal">{s.label}</th>)}<th className="text-right font-normal">Cost</th></tr></thead>
            <tbody>{m.series.map((d: any) => <tr key={d.day}><td>{d.day}</td>{SERIES.map((s) => <td key={s.key} className="text-right">{fmtTokens(d[s.key])}</td>)}<td className="text-right">{fmtUsd(d.cost)}</td></tr>)}</tbody>
          </table>
        </div>
      ) : (
        <div className="h-40 px-1 pt-1">
          <ChartSlot><TokensChart data={m.series} series={SERIES} /></ChartSlot>
        </div>
      )}

      <div className="px-3 pt-2 text-[13px] font-medium">Cost per day</div>
      <div className="h-24 px-1">
        <ChartSlot><CostChart data={m.series} /></ChartSlot>
      </div>

      <div className="grid grid-cols-2 gap-4 px-3 py-3 text-[12.5px] border-t border-line mt-2">
        <div>
          <div className="label mb-1">Effort used</div>
          {efforts.map(([k, v]) => (
            <div key={k} className="flex items-center gap-2 py-0.5">
              <span className="w-14 text-muted">{k}</span>
              <span className="flex-1 h-2 rounded-sm bg-sunken overflow-hidden"><span className="block h-full rounded-sm" style={{ width: `${(v / effortTotal) * 100}%`, background: ["xhigh", "max"].includes(k) ? "var(--warn)" : "var(--s1)" }} /></span>
              <span className="w-8 text-right tabular-nums">{v}</span>
            </div>
          ))}
        </div>
        <div>
          <div className="label mb-1">Top sessions by cost</div>
          {m.top_sessions.map((s: any) => (
            <button key={s.session_id} className="w-full flex gap-2 py-0.5 text-left hover:text-action" onClick={() => actions.openSession(s.session_id)}>
              <span className="truncate flex-1">{s.title}</span><span className="tabular-nums text-muted">{fmtUsd(s.cost)}</span>
            </button>
          ))}
          {!m.top_sessions.length && <div className="text-muted">—</div>}
        </div>
      </div>
    </section>
  );
}

function ElevenCard({ e }: { e: any }) {
  // One quota per ElevenLabs account; with more than one, a picker chooses which the card shows.
  const quotas: any[] = e.quotas ?? [];
  const [picked, setPicked] = useState<string | null>(null);
  const shown = quotas.find((x) => x.profile === picked) ?? quotas.find((x) => x.profile === e.profile)
    ?? { profile: e.profile, quota: e.quota, quota_checked_at: e.quota_checked_at, status: e.status };
  const q = shown.quota;
  const pct = q?.character_limit ? Math.min(1, q.character_count / q.character_limit) : null;
  return (
    <section className="rounded-md border border-line surface" aria-label="ElevenLabs usage">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-line">
        <ProviderDot provider="elevenlabs" /><span className="font-medium">ElevenLabs</span>
        {quotas.length > 1 && (
          <select className="input py-0.5 w-auto text-[12px] ml-2" value={shown.profile} onChange={(ev) => setPicked(ev.target.value)} aria-label="ElevenLabs account">
            {quotas.map((x) => <option key={x.profile}>{x.profile}</option>)}
          </select>
        )}
        <span className="ml-auto"><StatusBadge status={shown.status} /></span>
      </div>
      {q && (
        <div className="px-3 pt-3 text-[13px]">
          <div className="flex justify-between"><span>Credits used</span><span className="tabular-nums">{q.character_count?.toLocaleString()} of {q.character_limit?.toLocaleString()}</span></div>
          <div className="h-2 rounded-sm bg-sunken mt-1 overflow-hidden"><div className="h-full" style={{ width: `${(pct ?? 0) * 100}%`, background: (pct ?? 0) > 0.9 ? "var(--bad)" : "var(--eleven)" }} /></div>
          <div className="text-[12px] text-muted mt-1">{(q.character_limit - q.character_count).toLocaleString()} left · resets {q.next_character_count_reset_unix ? new Date(q.next_character_count_reset_unix * 1000).toLocaleDateString() : "—"} · {q.tier} plan</div>
          {shown.quota_checked_at && <div className="text-[11.5px] text-faint" title={new Date(shown.quota_checked_at * 1000).toLocaleString()}>Quota updated {fmtAgo(shown.quota_checked_at)}; refreshed after each generation</div>}
        </div>
      )}
      <div className="px-3 pt-3 flex items-center gap-3 text-[12px] flex-wrap">
        <span className="font-medium text-[13px]">By day</span>
        <span className="inline-flex items-center gap-1 text-muted"><span className="size-2.5 rounded-sm" style={{ background: "var(--eleven)" }} aria-hidden />Credits <span className="text-text tabular-nums">{fmtTokens(e.total_credits)}</span></span>
        <span className="inline-flex items-center gap-1 text-muted"><span className="size-2.5 rounded-sm" style={{ background: "var(--s1)" }} aria-hidden />Characters <span className="text-text tabular-nums">{fmtTokens(e.total_characters)}</span></span>
      </div>
      <div className="h-32 px-1">
        <ChartSlot><ElevenChart data={e.series} /></ChartSlot>
      </div>
      <div className="grid grid-cols-2 gap-4 px-3 py-3 text-[12.5px]">
        <div><div className="label mb-1">By feature</div>{e.by_feature.map((x: any) => <div key={x.feature} className="flex justify-between"><span>{x.feature}</span><span className="tabular-nums">{fmtTokens(x.amount)}</span></div>)}</div>
        <div><div className="label mb-1">By voice</div>{e.by_voice.map((x: any) => <div key={x.voice} className="flex justify-between"><span className="truncate">{x.voice}</span><span className="tabular-nums">{fmtTokens(x.amount)}</span></div>)}{!e.by_voice.length && <div className="text-muted">—</div>}</div>
      </div>
    </section>
  );
}
