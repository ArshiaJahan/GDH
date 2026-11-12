"""Scheduled tasks use standard cron weekday numbers (0 and 7 = Sunday), not APScheduler 3's (0 = Monday)."""
import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from workspace.features.tasks_feature import cron_trigger, cron_weekdays, make_trigger

TZ = ZoneInfo("Europe/Berlin")
# Saturday 2026-11-07 12:00 local: a weekend start, so "weekdays" must skip to Monday.
SAT = dt.datetime(2026, 11, 7, 12, 0, tzinfo=TZ)


def fires(expr: str, n: int = 7, start: dt.datetime = SAT) -> list[str]:
    """The next n fire times as 'Mon 09 08:30'."""
    trig = make_trigger(expr)
    trig.timezone = TZ  # pin the zone so the test doesn't depend on the machine's
    out, prev, now = [], None, start
    for _ in range(n):
        nxt = trig.get_next_fire_time(prev, now)
        out.append(nxt.astimezone(TZ).strftime("%a %d %H:%M"))
        prev, now = nxt, nxt + dt.timedelta(seconds=1)
    return out


def days(expr: str, n: int = 7) -> list[str]:
    return [f.split()[0] for f in fires(expr, n)]


def test_weekday_range_is_monday_to_friday():
    assert fires("0 8 * * 1-5", 6) == ["Mon 09 08:00", "Tue 10 08:00", "Wed 11 08:00", "Thu 12 08:00",
                                       "Fri 13 08:00", "Mon 16 08:00"]
    assert days("30 8 * * 1-5", 5) == ["Mon", "Tue", "Wed", "Thu", "Fri"]


@pytest.mark.parametrize("dow", ["0", "7", "sun", "SUN", "Sunday"])
def test_sunday_is_0_and_7(dow):
    assert fires(f"0 9 * * {dow}", 2) == ["Sun 08 09:00", "Sun 15 09:00"]


def test_single_days():
    assert days("0 9 * * 1", 2) == ["Mon", "Mon"]
    assert fires("0 17 * * 5", 1) == ["Fri 13 17:00"]
    assert fires("0 17 * * 6", 1) == ["Sat 07 17:00"]  # later today


def test_lists_and_names():
    assert days("0 9 * * 1,3,5", 4) == ["Mon", "Wed", "Fri", "Mon"]
    assert days("0 9 * * mon,wed,fri", 3) == ["Mon", "Wed", "Fri"]
    assert days("0 9 * * mon-fri", 5) == ["Mon", "Tue", "Wed", "Thu", "Fri"]
    assert days("0 9 * * 0,6", 3) == ["Sun", "Sat", "Sun"]
    assert days("0 9 * * sat-sun", 3) == ["Sun", "Sat", "Sun"]
    assert days("0 9 * * 5-7", 4) == ["Sun", "Fri", "Sat", "Sun"]


def test_steps():
    assert cron_weekdays("*/2") == {0, 2, 4, 6}
    assert cron_weekdays("1-5/2") == {1, 3, 5}
    assert cron_weekdays("1/2") == {1, 3, 5}
    assert days("0 9 * * 1-5/2", 3) == ["Mon", "Wed", "Fri"]
    assert days("0 9 * * */2", 4) == ["Sun", "Tue", "Thu", "Sat"]


def test_every_day_forms():
    for f in ["*", "0-6", "0-7", "1-7", "*/1"]:
        assert cron_weekdays(f) == set(range(7))
    assert days("0 9 * * *", 7) == ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    # Other fields pass through untouched.
    assert fires("*/15 9-10 * * 1", 3) == ["Mon 09 09:00", "Mon 09 09:15", "Mon 09 09:30"]
    assert fires("0 9 1 * *", 1) == ["Tue 01 09:00"]


def test_presets_match_their_labels():
    # frontend/src/pages/Tasks.tsx PRESETS
    assert days("30 8 * * 1-5", 5) == ["Mon", "Tue", "Wed", "Thu", "Fri"]
    assert fires("0 9 * * 1", 1) == ["Mon 09 09:00"]
    assert fires("0 9 * * *", 1) == ["Sun 08 09:00"]
    assert fires("0 * * * *", 2) == ["Sat 07 12:00", "Sat 07 13:00"]  # now included
    assert fires("every:30m", 2) == ["Sat 07 12:00", "Sat 07 12:30"]


@pytest.mark.parametrize("bad", ["0 9 * * 8", "0 9 * * 5-1", "0 9 * * funday", "0 9 * * 1,", "0 9 * * */0",
                                 "0 9 * *", "0 9 * * 1 2"])
def test_rejects_bad_weekdays(bad):
    with pytest.raises(ValueError):
        cron_trigger(bad)
