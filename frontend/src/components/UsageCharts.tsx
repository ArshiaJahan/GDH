// The My usage charts. Recharts is large, so this module is its own chunk: the Usage page
// loads it with React.lazy and shows its numbers before the charts arrive.
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fmtTokens, fmtUsd } from "./ui";

export type Series = { key: string; label: string; color: string; hint?: string };

const tipStyle = { background: "var(--raised)", border: "1px solid var(--line)", borderRadius: 6, fontSize: 12, color: "var(--text)" };
const axis = { stroke: "var(--faint)", fontSize: 11, tickLine: false, axisLine: false } as const;

export function TokensChart({ data, series }: { data: any[]; series: Series[] }) {
  return (
    <ResponsiveContainer>
      <BarChart data={data} margin={{ top: 6, right: 8, left: 0, bottom: 0 }} barCategoryGap="28%">
        <CartesianGrid vertical={false} stroke="var(--line)" strokeDasharray="0" />
        <XAxis dataKey="day" {...axis} tickFormatter={(d) => d.slice(5)} />
        <YAxis {...axis} width={44} tickFormatter={fmtTokens} />
        <Tooltip contentStyle={tipStyle} cursor={{ fill: "var(--sunken)" }} formatter={(v: any, n: any) => [fmtTokens(v), series.find((s) => s.key === n)?.label ?? n]} />
        {series.map((s, i) => (
          <Bar key={s.key} dataKey={s.key} stackId="t" fill={s.color} stroke="var(--panel)" strokeWidth={1}
            radius={i === series.length - 1 ? [3, 3, 0, 0] : undefined} maxBarSize={28} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

export function CostChart({ data }: { data: any[] }) {
  return (
    <ResponsiveContainer>
      <LineChart data={data} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid vertical={false} stroke="var(--line)" />
        <XAxis dataKey="day" {...axis} tickFormatter={(d) => d.slice(5)} />
        <YAxis {...axis} width={44} tickFormatter={(v) => fmtUsd(v)} />
        <Tooltip contentStyle={tipStyle} formatter={(v: any) => [fmtUsd(v), "Cost"]} />
        <Line dataKey="cost" stroke="var(--action)" strokeWidth={2} dot={data.length < 3 ? { r: 4 } : false} activeDot={{ r: 4 }} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

export function ElevenChart({ data }: { data: any[] }) {
  return (
    <ResponsiveContainer>
      <BarChart data={data} margin={{ top: 6, right: 8, left: 0, bottom: 0 }} barGap={2}>
        <CartesianGrid vertical={false} stroke="var(--line)" />
        <XAxis dataKey="day" {...axis} tickFormatter={(d) => d.slice(5)} />
        <YAxis {...axis} width={44} tickFormatter={fmtTokens} />
        <Tooltip contentStyle={tipStyle} cursor={{ fill: "var(--sunken)" }} formatter={(v: any, n: any) => [Math.round(v).toLocaleString(), n]} />
        <Bar dataKey="credits" name="Credits" fill="var(--eleven)" radius={[3, 3, 0, 0]} maxBarSize={22} />
        <Bar dataKey="characters" name="Characters" fill="var(--s1)" radius={[3, 3, 0, 0]} maxBarSize={22} />
      </BarChart>
    </ResponsiveContainer>
  );
}
