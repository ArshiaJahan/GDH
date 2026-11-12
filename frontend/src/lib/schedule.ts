// Task schedules in words. Weekdays follow standard cron (0 and 7 = Sunday), the same reading
// the backend gives them (backend/gamedevworkstation/features/tasks_feature.py, cron_weekdays).

export const PRESETS: [string, string][] = [
  ["Every weekday at 8:30", "30 8 * * 1-5"],
  ["Every day at 9:00", "0 9 * * *"],
  ["Every Monday at 9:00", "0 9 * * 1"],
  ["Every hour", "0 * * * *"],
  ["Every 30 minutes", "every:30m"],
];

const NAMES = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];
const FULL = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"];
const SHORT = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const LONG = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MON_FIRST = [1, 2, 3, 4, 5, 6, 0];

/** One 24-hour clock everywhere a task time is shown. */
export const TIME_FORMAT: Intl.DateTimeFormatOptions = {
  weekday: "short", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
};

function day(token: string, end = false): number | null {
  const t = token.toLowerCase();
  if (/^\d+$/.test(t)) return +t <= 7 ? +t : null;
  const n = NAMES.indexOf(t) >= 0 ? NAMES.indexOf(t) : FULL.indexOf(t);
  if (n < 0) return null;
  return end && n === 0 ? 7 : n;
}

/** The weekdays (0 = Sunday … 6 = Saturday) a cron day-of-week field names, or null if it can't be read. */
export function cronWeekdays(field: string): Set<number> | null {
  const days = new Set<number>();
  for (const part of field.split(",")) {
    const [rng, stepS, extra] = part.split("/");
    if (!rng || extra !== undefined || (stepS !== undefined && !/^[1-9]\d*$/.test(stepS))) return null;
    const step = stepS ? +stepS : 1;
    let lo: number | null, hi: number | null;
    if (rng === "*") [lo, hi] = [0, 6];
    else if (rng.includes("-")) {
      const [a, b] = rng.split("-");
      [lo, hi] = [day(a), day(b, true)];
      if (lo === null || hi === null || hi < lo) return null;
    } else {
      lo = day(rng);
      if (lo === null) return null;
      hi = stepS ? Math.max(lo, 6) : lo;
    }
    for (let d = lo; d <= hi; d += step) days.add(d % 7);
  }
  return days;
}

/** "every day", "weekdays", "Tue–Thu", "Mon, Wed and Fri" — Monday first, runs of 3+ as a range. */
function daysPhrase(days: Set<number>): { every: string; on: string } {
  if (days.size === 7) return { every: "Every day", on: "" };
  const order = MON_FIRST.filter((d) => days.has(d));
  if (order.length === 5 && [1, 2, 3, 4, 5].every((d) => days.has(d))) return { every: "Every weekday", on: "on weekdays" };
  if (order.length === 1) return { every: `Every ${LONG[order[0]]}`, on: `on ${LONG[order[0]]}s` };
  const parts: string[] = [];
  for (let i = 0; i < order.length;) {
    let j = i;
    while (j + 1 < order.length && MON_FIRST.indexOf(order[j + 1]) === MON_FIRST.indexOf(order[j]) + 1) j++;
    if (j - i >= 2) parts.push(`${SHORT[order[i]]}–${SHORT[order[j]]}`);
    else for (let k = i; k <= j; k++) parts.push(SHORT[order[k]]);
    i = j + 1;
  }
  const list = parts.length === 1 ? parts[0] : `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
  return { every: `Every ${list}`, on: `on ${list}` };
}

const ordinal = (n: number) => `${n}${n % 10 === 1 && n !== 11 ? "st" : n % 10 === 2 && n !== 12 ? "nd" : n % 10 === 3 && n !== 13 ? "rd" : "th"}`;

export function describeSchedule(schedule: string): string {
  const s = schedule.trim();
  const preset = PRESETS.find(([, v]) => v === s);
  if (preset) return preset[0];
  if (s.startsWith("once:")) {
    const d = new Date(s.slice(5));
    return isNaN(+d) ? `once ${s.slice(5)}` : `Once, ${d.toLocaleString([], { ...TIME_FORMAT, year: "numeric" })}`;
  }
  const every = /^every:(\d+)([mh])$/.exec(s);
  if (every) {
    const n = +every[1];
    const unit = every[2] === "h" ? "hour" : "minute";
    return n === 1 ? `Every ${unit}` : `Every ${n} ${unit}s`;
  }
  const p = s.split(/\s+/);
  if (p.length !== 5) return `cron ${s}`;
  const [min, hour, dom, mon, dow] = p;
  const days = cronWeekdays(dow);
  if (!days || mon !== "*") return `cron ${s}`;
  const num = (x: string, max: number) => /^\d+$/.test(x) && +x <= max;
  const { every: everyDays, on } = daysPhrase(days);
  const suffix = on ? ` ${on}` : "";
  if (dom !== "*") {
    if (!num(dom, 31) || days.size !== 7 || !num(min, 59) || !num(hour, 23)) return `cron ${s}`;
    return `Monthly on the ${ordinal(+dom)} at ${hour}:${min.padStart(2, "0")}`;
  }
  if (num(min, 59) && num(hour, 23)) return `${everyDays} at ${+hour}:${min.padStart(2, "0")}`;
  if (num(min, 59) && hour === "*") return `${+min === 0 ? "Every hour" : `Every hour at :${min.padStart(2, "0")}`}${suffix}`;
  const step = /^\*\/(\d+)$/.exec(min);
  if (step && hour === "*") return `Every ${+step[1] === 1 ? "minute" : `${+step[1]} minutes`}${suffix}`;
  return `cron ${s}`;
}
