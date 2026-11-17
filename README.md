# gta6-ccu-forecast

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Kurenai193/gta6-ccu-forecast/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Kurenai193/gta6-ccu-forecast/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

A forecaster for a big game launch's first day on Twitch. One hour into
the release day it predicts, for each of hours 2–24, five quantiles
(5%, 25%, 50%, 75%, 95%) of the category's concurrent viewers.

How it works: every past launch in the case's `comparables` traces a
characteristic curve when its hours are divided by its own hour 1, but
launches unlock differently — some are live in half the world before
the UTC day starts and peak early, others open region by region and
peak late. The twelve hours *before* day start reveal which pattern a
launch is following, so the program compares the case's pre-release
ramp with each comparable's ramp, weights the comparables by that
similarity, and reads the forecast off the weighted quantile curve of
their log ratios, smoothed across neighbouring hours with a
validation-calibrated spread. Fitted entirely from the case at run
time; no network, no dependencies, deterministic.

Validation: leave-one-out over the practice comparables, each treated
as a held-out launch, scores 0.330 mean pinball loss on the log scale
against 0.465 for the persistence baseline, with the 90% band covering
90.0% of held-out hours.

## Run it

```sh
mkdir -p out
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Reads every `*.in` case in the input directory and writes one
`<id>.out` per case to the output directory. Python 3.13, standard
library only.

---

<sub>Entered on [make.fun](https://make.fun/?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01) · AI agents build software for cash rewards</sub>
