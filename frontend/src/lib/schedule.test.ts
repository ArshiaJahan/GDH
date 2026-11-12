import { describe, expect, it } from "vitest";
import { PRESETS, cronWeekdays, describeSchedule } from "./schedule";

const set = (...d: number[]) => new Set(d);

describe("cronWeekdays", () => {
  it("reads cron numbering, with 0 and 7 as Sunday", () => {
    expect(cronWeekdays("1-5")).toEqual(set(1, 2, 3, 4, 5));
    expect(cronWeekdays("0")).toEqual(set(0));
    expect(cronWeekdays("7")).toEqual(set(0));
    expect(cronWeekdays("5-7")).toEqual(set(5, 6, 0));
    expect(cronWeekdays("*")).toEqual(set(0, 1, 2, 3, 4, 5, 6));
  });
  it("reads lists, steps and names", () => {
    expect(cronWeekdays("1,3,5")).toEqual(set(1, 3, 5));
    expect(cronWeekdays("*/2")).toEqual(set(0, 2, 4, 6));
    expect(cronWeekdays("1-5/2")).toEqual(set(1, 3, 5));
    expect(cronWeekdays("mon-fri")).toEqual(set(1, 2, 3, 4, 5));
    expect(cronWeekdays("SAT-sun")).toEqual(set(6, 0));
  });
  it("rejects what the backend rejects", () => {
    for (const bad of ["8", "5-1", "funday", "1,", "*/0"]) expect(cronWeekdays(bad)).toBeNull();
  });
});

describe("describeSchedule", () => {
  it("names weekday ranges and lists", () => {
    expect(describeSchedule("0 8 * * 1-5")).toBe("Every weekday at 8:00");
    expect(describeSchedule("15 7 * * mon-fri")).toBe("Every weekday at 7:15");
    expect(describeSchedule("0 17 * * 5")).toBe("Every Friday at 17:00");
    expect(describeSchedule("0 9 * * 0")).toBe("Every Sunday at 9:00");
    expect(describeSchedule("0 9 * * 7")).toBe("Every Sunday at 9:00");
    expect(describeSchedule("0 9 * * 2-4")).toBe("Every Tue–Thu at 9:00");
    expect(describeSchedule("0 9 * * 1,3,5")).toBe("Every Mon, Wed and Fri at 9:00");
    expect(describeSchedule("0 10 * * 0,6")).toBe("Every Sat and Sun at 10:00");
    expect(describeSchedule("0 10 * * 5-7")).toBe("Every Fri–Sun at 10:00");
    expect(describeSchedule("0 9 * * *")).toBe("Every day at 9:00");
  });
  it("describes hourly, minute steps, monthly and intervals", () => {
    expect(describeSchedule("5 * * * *")).toBe("Every hour at :05");
    expect(describeSchedule("0 * * * 1-5")).toBe("Every hour on weekdays");
    expect(describeSchedule("*/15 * * * *")).toBe("Every 15 minutes");
    expect(describeSchedule("0 9 1 * *")).toBe("Monthly on the 1st at 9:00");
    expect(describeSchedule("every:2h")).toBe("Every 2 hours");
    expect(describeSchedule("every:1h")).toBe("Every hour");
    expect(describeSchedule("every:45m")).toBe("Every 45 minutes");
  });
  it("falls back to the raw line when it can't say it in words", () => {
    expect(describeSchedule("0 9-17 * * 1-5")).toBe("cron 0 9-17 * * 1-5");
    expect(describeSchedule("0 9 * 6 *")).toBe("cron 0 9 * 6 *");
  });
  it("agrees with every preset label", () => {
    for (const [label, cron] of PRESETS) expect(describeSchedule(cron)).toBe(label);
    // The generic wording for an equivalent line matches the preset's own.
    expect(describeSchedule("30 8 * * mon-fri")).toBe("Every weekday at 8:30");
    expect(describeSchedule("0 9 * * mon")).toBe("Every Monday at 9:00");
  });
});
