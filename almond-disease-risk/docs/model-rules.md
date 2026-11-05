# Model Rules

These are the rules the predictor uses to turn hourly weather into a daily disease-risk rating. Last updated 5 November 2025.

All calculations use **Australia/Melbourne** local time, so daily cycles line up with actual daylight and rainfall.

## Weather processing

| Rule | Logic | Why it matters |
|---|---|---|
| **Wetness flag** (hourly) | An hour is wet if it rained (precipitation > 0), **or** relative humidity is ≥ 95 % and air temp − dew point ≤ 1 °C. | Tells us when leaves are likely covered in rain or dew. |
| **Wet hours** (daily) | Counts the wet hours in a day. | Shows how long leaves stayed wet that day. |
| **Longest wet run** (streak) | Consecutive wet hours across the whole timeline. A dry gap of **≥ 4 h** resets the streak to 0; shorter dry breaks are tolerated. Runs can carry over midnight. | Some diseases need long, unbroken wet periods that can span days. |
| **Hourly leaf temperature** | Air temperature **+5 °C** on clear, sunny hours (cloud cover ≤ 20 % **and** shortwave radiation > 100 W/m²). | Approximates sunlight heating the leaf above air temperature (literature reports 5–10 °C). The 100 W/m² cut-off limits the boost to daytime. |
| **Daily temperature for scoring** | Mean of the hourly leaf temperatures for the day. | One representative leaf-level temperature per day. |

## Anthracnose score (max 7)

| Factor | Points |
|---|---|
| **Wetness** (longest wet run) | ≥ 23 h → 3 · ≥ 12 h → 2 · ≥ 6 h → 1 |
| **Temperature** (avg leaf temp) | 10–25 °C → 3 · 5–10 °C or 25–30 °C → 1 |
| **Wind** (daily max at 10 m) | ≥ 36 km/h → +1 |

The fungus needs time to infect: around 24 h of wetness for leaves and around 3 h for blossoms. It favours mild-to-warm weather, and wind helps spread spores. The 36 km/h threshold (≈ 10 m/s) comes from Rogers & Kimpton (2011) on spore liberation.

## Bacterial spot score (max 7)

| Factor | Points |
|---|---|
| **Wetness** (longest wet run) | ≥ 23 h → 3 · ≥ 22 h → 2 · ≥ 21 h → 1 |
| **Temperature** (avg leaf temp) | 25–30 °C → 3 · 10–25 °C or 30–35 °C → 2 · other temps ≥ 5 °C → 1 |
| **Wind** (daily max at 10 m) | ≥ 36 km/h → +1 |

Bacterial spot needs long, uninterrupted wet periods (around 24 h). Warm temperatures boost bacterial activity, and wind-driven rain carries bacteria between leaves.

> If the longest wet run is 0 hours, both scores are 0 no matter what the temperature or wind is.

## Risk category

| Total score | Risk | Colour |
|---|---|---|
| ≥ 6 | High | Red |
| ≥ 4 | Medium | Yellow |
| < 4 | Low | Green |
