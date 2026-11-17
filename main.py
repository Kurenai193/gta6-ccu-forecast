"""Launch-day Twitch viewer forecaster for gta6-twitch-ccu-forecast-01.

Model, in one paragraph: a launch's release day has a characteristic
shape when every hour is divided by that day's first hour. Past big
launches (the case's `comparables`) trace that shape out many times,
but they do not all unlock the same way: some are already live in half
the world before the UTC day starts and peak early, others only open
region by region during the day and peak late. The hours *before* the
release day reveal which pattern a launch is following, so this
program compares the case's own pre-release ramp (the twelve hours
before day start, each as a log ratio to hour 1) with every
comparable's ramp and weights the comparables by that similarity.
The forecast for each hour is then the similarity-weighted quantile
curve of the comparables' log ratios, smoothed across neighbouring
hours, with the spread widened by a factor that leave-one-out
validation over the comparables showed to be calibrated (90% band
covering about 90% of held-out hours).

Runs offline, standard library only, deterministic: the same case
always writes the same bytes.
"""

import json
import math
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# The grader runs this file with -P, which leaves its own directory off
# sys.path; put it back first so sibling modules would import.
sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.645, -0.674, 0.0, 0.674, 1.645]
FIRST_FORECAST_HOUR = 2
LAST_HOUR = 24

# How many hours before day start form the pre-release ramp signature.
PREDAY_HOURS = 12
# Similarity weighting: a Gaussian kernel over the ramp distance, with
# a floor so no comparable is ever fully ignored (robustness when the
# target's ramp matches nothing in the set).
WEIGHT_SIGMA = 0.45
WEIGHT_FLOOR = 0.02
# Neighbouring hours share shape, so quantile curves are averaged over
# a window of this width before use.
SMOOTH_WINDOW = 3
# The raw cross-launch spread is a little narrow for a single unseen
# launch; widening it by this factor calibrated the 90% band in
# leave-one-out validation.
SPREAD_SCALE = 1.20
# Fallback spread (the house baseline's) for an hour no comparable
# covers: log-space sigma per square-root hour from hour 1.
FALLBACK_SIGMA = 0.15


def parse_time(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def hourly_map(rows, key):
    """Map timestamps to viewer counts from a list of hourly rows."""
    result = {}
    for row in rows or []:
        stamp = row.get(key)
        viewers = row.get("viewers")
        if stamp is None or viewers is None:
            continue
        result[parse_time(stamp)] = viewers
    return result


def aggregate_hourly(rows):
    """Hourly means from minute-level rows (the final case's `history`).

    Each row's timestamp is floored to its hour and the viewers of all
    rows inside the hour are averaged, matching how an hour's print is
    defined for the final case.
    """
    totals = {}
    counts = {}
    for row in rows or []:
        stamp = row.get("at")
        viewers = row.get("viewers")
        if stamp is None or viewers is None:
            continue
        hour_start = parse_time(stamp).replace(minute=0, second=0, microsecond=0)
        totals[hour_start] = totals.get(hour_start, 0.0) + viewers
        counts[hour_start] = counts.get(hour_start, 0) + 1
    return {hour: totals[hour] / counts[hour] for hour in totals}


def release_curve(comp):
    """The comparable's release-day hours: {hour 1..24: viewers}."""
    start = parse_time(comp["day_start"])
    by_time = hourly_map(comp.get("hourly"), "from")
    curve = {}
    for hour in range(1, LAST_HOUR + 1):
        value = by_time.get(start + timedelta(hours=hour - 1))
        if value is not None:
            curve[hour] = value
    return curve, by_time, start


def preday_log_ratios(by_time, start, anchor):
    """Log ratios of the PREDAY_HOURS before day start to the anchor.

    The anchor is hour 1's print, so the signature describes how much
    of the audience was already there before the UTC day began.
    """
    if not anchor or anchor <= 0:
        return {}
    ratios = {}
    for offset in range(-PREDAY_HOURS, 0):
        value = by_time.get(start + timedelta(hours=offset))
        if value is not None and value > 0:
            ratios[offset] = math.log(value / anchor)
    return ratios


def ramp_distance(first, second):
    """Root-mean-square difference over the offsets both ramps share."""
    diffs = []
    for offset, value in first.items():
        if offset in second:
            diffs.append((value - second[offset]) ** 2)
    if not diffs:
        return None
    return math.sqrt(sum(diffs) / len(diffs))


def similarity_weight(distance):
    if distance is None:
        return 1.0
    return math.exp(-0.5 * (distance / WEIGHT_SIGMA) ** 2) + WEIGHT_FLOOR


def weighted_quantile(pairs, tau):
    """Quantile of (value, weight) pairs by cumulative weight mass."""
    ordered = sorted(pairs)
    total = sum(weight for _, weight in ordered)
    if total <= 0:
        return plain_quantile([value for value, _ in ordered], tau)
    target = tau * total
    acc = 0.0
    for index, (value, weight) in enumerate(ordered):
        acc += weight
        if acc >= target:
            if index == 0:
                return value
            prev_value = ordered[index - 1][0]
            before = acc - weight
            if weight <= 0:
                return value
            frac = (target - before) / weight
            return prev_value + frac * (value - prev_value)
    return ordered[-1][0]


def plain_quantile(sorted_values, tau):
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = tau * (len(sorted_values) - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = pos - lo
    return sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac


def fit_ratio_curves(case, p1):
    """Fit {hour: [log-ratio quantiles]} from the case's comparables."""
    game_name = (case.get("game") or {}).get("name") or ""
    day_start = parse_time(case["day_start"])
    # The target's own ramp: hourly rows where the case provides them,
    # with any missing hour filled from the minute-level history
    # aggregated to hourly means (the final case records minutes).
    target_map = aggregate_hourly(case.get("history"))
    target_map.update(hourly_map(case.get("history_hourly"), "from"))
    target_ramp = preday_log_ratios(target_map, day_start, p1)

    per_hour = {hour: [] for hour in range(FIRST_FORECAST_HOUR, LAST_HOUR + 1)}
    for comp in case.get("comparables") or []:
        name = comp.get("name") or ""
        # The target category's own pre-release listing is not a launch
        # comparable; its "release day" is a trailer premiere, so the
        # curve it would contribute does not describe a launch day.
        if game_name and name.startswith(game_name):
            continue
        if "before release" in name:
            continue
        curve, by_time, start = release_curve(comp)
        v1 = curve.get(1)
        if not v1 or v1 <= 0:
            continue
        comp_ramp = preday_log_ratios(by_time, start, v1)
        weight = similarity_weight(ramp_distance(target_ramp, comp_ramp))
        for hour in range(FIRST_FORECAST_HOUR, LAST_HOUR + 1):
            value = curve.get(hour)
            if value is not None and value > 0:
                per_hour[hour].append((math.log(value / v1), weight))

    raw = {}
    for hour, entries in per_hour.items():
        if entries:
            raw[hour] = [weighted_quantile(entries, tau) for tau in LEVELS]
        else:
            sigma = FALLBACK_SIGMA * math.sqrt(hour - 1)
            raw[hour] = [z * sigma for z in Z]

    half = SMOOTH_WINDOW // 2
    smoothed = {}
    for hour in raw:
        acc = [0.0] * len(LEVELS)
        count = 0
        for other in range(hour - half, hour + half + 1):
            if other in raw:
                for i in range(len(LEVELS)):
                    acc[i] += raw[other][i]
                count += 1
        smoothed[hour] = [value / count for value in acc]

    fitted = {}
    for hour, quantiles in smoothed.items():
        median = quantiles[2]
        widened = [median + SPREAD_SCALE * (q - median) for q in quantiles]
        # Keep the five quantiles ordered even after smoothing/widening.
        ordered = []
        for q in widened:
            ordered.append(q if not ordered else max(q, ordered[-1]))
        fitted[hour] = ordered
    return fitted


def round2(x):
    """Round to 2 decimals, half up; whole numbers come back as int."""
    scaled = x * 100
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 100
    return int(value) if float(value).is_integer() else value


def clamp_viewers(value):
    if value <= 0:
        return 0.01
    if value > 1e9:
        return 1e9
    return value


def forecast_case(case):
    first = next((row for row in case.get("known") or [] if row.get("hour") == 1), None)
    if first is None:
        raise ValueError("case has no hour-1 print")
    p1 = max(1, first["viewers"])
    ratios = fit_ratio_curves(case, p1)
    rows = []
    wanted = case.get("forecast") or [{"hour": h} for h in range(FIRST_FORECAST_HOUR, LAST_HOUR + 1)]
    for row in wanted:
        hour = row["hour"]
        quantiles = ratios.get(hour)
        if quantiles is None:
            sigma = FALLBACK_SIGMA * math.sqrt(hour - 1)
            quantiles = [z * sigma for z in Z]
        values = [round2(clamp_viewers(p1 * math.exp(q))) for q in quantiles]
        rows.append({"hour": hour, "q": values})
    return {"hours": rows}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case)
        out_path = OUTPUT_DIR / f"{path.stem}.out"
        out_path.write_text(json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
