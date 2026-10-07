# Analytics: metric definitions and results

Every percentage, index and derived figure the dashboard shows, exactly how it is computed, and the results. Model
names are dbt models (schema in brackets). **Days are UTC calendar days everywhere** (`marts.fact_player_activity_daily`
and the models built on it); hourly timestamps are displayed in Berlin time and labelled so. N and every result are
the values in the published snapshot of 2026-10-07 ([DATA_SOURCES.md](DATA_SOURCES.md)); the dashboard always derives
N from the data, never from text.

Worked examples, SQL and baseline distributions for each metric, with the numbers of the 2026-09-29 build:
[tests/index_definitions_2026_09_29.md](tests/index_definitions_2026_09_29.md).

| Metric (page) | Formula | Baseline (100%) and window | Aggregation | Filters | N | Source model | Day definition |
|---|---|---|---|---|---|---|---|
| Change vs. last month (Overview movers, Game explorer "Players online, final reading") | `avg_7d / last_month_avg − 1` | The game's own monthly average for the last complete month (September 2026 for all games) | None, one value per game | Games with hourly readings and that month | 55 games | `fact_player_activity` (hourly), `fact_player_activity_monthly` [marts] | Timestamps: last 7 × 24 h before the final reading (2026-10-07 14:47 UTC) |
| % of launch peak (Q1 curves) | `avg_players / launch_peak_avg` | Launch peak = busiest monthly average from the release month to 3 months later | None per game | `lifecycle_status = 'launch_observed'`, months 0–24 | 53 games | `rpt_lifecycle_curve` [reporting] | Calendar months |
| Typical game (Q1 headline) | `median(vs_launch_peak)` per month since release; plateau = median of the monthly medians, months 4–18 | Launch peak | **Median across games**, per month | Settled games (≥ 1 year since launch) | 43 games (37–43 per month) | `rpt_lifecycle_typical_curve` [reporting] | Calendar months |
| Retention m6 / m12 / m24, latest vs. launch peak (Q1 table) | `m{6,12,24}_avg / launch_peak_avg`; `latest_avg_players / launch_peak_avg` | Launch peak | None | Launch observed; month must exist | 55 rows | `rpt_game_lifecycle` [reporting] | Calendar months |
| Lifecycle pattern (Q1 bars) | `m12_avg / launch_peak_avg`: < 0.30 front-loaded, < 0.60 gradual decline, ≤ 1.00 sustained, else growing | Launch peak | Count of games | Launch observed | 53 games (10 too new) | `rpt_game_lifecycle` | Calendar months |
| Comeback (Q1) | Lowest and latest month as % of launch peak | Launch peak; lowest = min month after the launch-peak month (`lowest_after_launch_players`) | None | Fell ≤ 50% of the launch peak, later a 3-month average ≥ 75% | 13 games | `rpt_game_lifecycle` | Calendar months |
| Change over 12 months (Q2 scatter) | `current_level_3m / start_level_3m − 1` | Mean of the first 3 months of the window (Oct–Dec 2025); window = the 12 months ending at the latest complete month (Oct 2025 – Sep 2026) | None | Judged classes (declining / growing / stable / volatile) | 48 games | `rpt_activity_health` [reporting] | Calendar months |
| Players vs. start of the year (Q2 lines) | `avg_players / start_level_3m` | Same start level | None | Picked games | 48 pickable | `rpt_activity_health`, `fact_player_activity_monthly` | Calendar months |
| Trend per month, health class (Q2) | `exp(slope of ln(players) on month) − 1`; class: ≥ ±3%/month with r² ≥ 0.5 → growing / declining; < 3% → stable; else volatile | — | Count of games | ≥ 9 of 12 months, first month before the window | 55 games | `rpt_activity_health` | Calendar months |
| Discount lift: during / first week / weeks 2–4 (Q3) | `phase_avg / baseline_avg − 1` | `baseline_avg` = mean daily players in the **14 days before** the discount; during = discount days; first week = days 1–7 after; weeks 2–4 = days 8–28 after | None per discount | Complete 5-minute days; valid = ≥ 12 baseline days, ≥ 80% of discount days, ≥ 15 post days, no discount in the 14 days before | 321 valid discounts | `rpt_discount_effect` [reporting] | UTC days |
| Discount outcome shares (Q3 bars) | Share of discounts per outcome: no lift (< 5% during), back to normal (weeks 2–4 within ±10%), stayed higher (> +10%), fell below | 14 days before | **Pooled across discounts** (count share) | Valid and not followed by another discount within 28 days | 174 discounts, 23 games | `rpt_discount_effect` | UTC days |
| Typical discount (Q3 header metrics "During a discount", "2–4 weeks after") | `median(lift_during)` and `median(lift_post_late)`, shown as signed % (e.g. +15.6% → +16%) | `baseline_avg` = mean daily players in the 14 days before each discount; weeks 2–4 = days 8–28 after it ends | **Median pooled across discounts** | As outcome shares (valid, no other discount within 28 days after) | 174 discounts, 23 games | `rpt_discount_typical` [reporting], group `all` | UTC days |
| Lift by discount depth (Q3 depth cards) | `median(lift_during)` per bucket of the episode's deepest discount: < 50%, 50–74%, ≥ 75% off; headline "deeper discounts bring more players" only if the ≥ 75% median is more than 10 points above both other buckets; "few cases" below 10 discounts | 14 days before | **Median pooled across discounts**, per bucket | As outcome shares | 52 / 86 / 36 discounts (12 / 16 / 8 games) | `rpt_discount_by_depth` [reporting] | UTC days |
| Players vs. before the discount (Q3 detail) | `avg_players / baseline_avg` per day | That discount's 14 days before; window 14 days before to 28 days after | None; one line per discount | Valid discounts; complete 5-minute days | 23 games | `rpt_discount_effect_daily` [reporting] | UTC days |
| Unusual day (Q4) | `z = (ln(players) − mean_28) / sd_28`; unusual when abs(z) ≥ 3; Steam-wide when ≥ 3 games move the same way that day | Previous 28 days (the day itself excluded), ln scale; needs ≥ 21 of them | None per game-day | Complete 5-minute days, players > 0 | 29 games; 375 flagged days (255 surges, 57 drops, 63 Steam-wide on 18 days) | `rpt_market_anomalies` [reporting] | UTC days |
| Expected range (Q4 detail band) | `exp(mean_28 ± 3·sd_28)`; baseline line `exp(mean_28)` | Previous 28 days | None | Scored days | — | `rpt_market_anomalies` (`baseline_players`, `band_lower_players`, `band_upper_players`) | UTC days |
| Surge rate by discount depth (Q4 bars, "13×") | `surges / days` per bucket (no discount; < 50% off; ≥ 50% off, by the episode's deepest discount); ratio = ≥ 50% rate / no-discount rate | — | **Pooled across game-days** | Scored days of games ever discounted; Steam-wide surges excluded | 21,715 game-days, 23 games | `rpt_market_anomalies` | UTC days |
| Busiest month (Game explorer metric) | `max(avg_players)`; secondary line `latest / max` | All-time busiest month (any month in the data) | None | — | 55 games | `fact_player_activity_monthly` [marts] | Calendar months |
| Positive reviews (Game explorer) | `avg(voted_up)` overall and per playtime bucket | — | None | Recent reviews; buckets ≥ 20 reviews | per game | `fact_reviews` [marts] | — |

## Results

Descriptive and associational: what coincided with what, not what caused what (BRD section 3).

| Question | Coverage | Result |
|---|---|---|
| Q1 Life after launch | 53 games with an observed launch; 43 of them at least one year old | The typical game holds 47% of its launch-peak players three months after launch and 43% from month 4 onward. One year after launch, 15 of the 43 games had dropped below 30% of their launch peak, 5 were at 30–60%, 11 at 60–100% and 12 above it. 13 games made a comeback; 4 of them were above their launch peak in September 2026 |
| Q2 Activity health | 48 games judged over Oct 2025 – Sep 2026 (7 too new) | 33 stable, 10 up-and-down, 3 growing, 2 declining |
| Q3 Discounts | 174 discounts in 23 games | During a discount the typical game had 16% more players than in the 14 days before, and 6% more two to four weeks after it ended. 41% of discounts stayed more than 10% higher in weeks 2–4, 33% went back to normal, 20% brought no bump, 6% fell below. By depth: +15% under 50% off, +14% at 50–74%, +20% at 75% or more |
| Q4 Unusual days | 29 games, 375 flagged days | 255 surges, 57 drops, 63 Steam-wide on 18 days. Surges were about 13 times as frequent on days with a discount of 50% or more (4.6% of days) as on days without one (0.35%) |

## Notes

- **Pooling.** The Q3 outcome bars, the Q3 depth cards and the Q4 surge ratio pool discounts or days across games, so a
  game with many discounts or days weighs more. The per-game spread and a sensitivity check (2026-09-29 build):
  [tests/index_consistency_2026_09_29.md](tests/index_consistency_2026_09_29.md).
- **Monthly sources.** Monthly averages come from SteamCharts; the Kaggle dataset is read only for months SteamCharts
  lacks, and no month in the snapshot needed it. The 7-day average on the Overview comes from the project's own hourly
  collector; the two are compared directly.
- **Final 7 days.** The 7 days before the final reading include the 5–7 Oct collection gap
  ([TRD section 13.1](TRD.md#131-collection-incidents)), so `avg_7d` averages the readings that exist.

## Limitations

### Unusual days (Q4)

- **Masking after a spike (baseline contamination).** The 28-day window that sets the baseline and the expected range
  does not leave out days that were themselves flagged. After a spike, the spike days stay in the window for the next
  28 days: they raise `sd_28` and widen the expected range for that whole period, so a second event inside those
  28 days can be missed. The Q4 detail chart shows this as a band that balloons right after a spike and slowly
  narrows again.
- **Gradual trends are not flagged, by design.** The detector compares each day with the 28 days just before it, so a
  slow rise or fall moves the baseline along with it. Only sudden jumps or drops leave the expected range; long-run
  direction is what the Activity health page (Q2) measures.
- **Future work: a robust baseline.** Replace mean / standard deviation with a rolling median and MAD (median absolute
  deviation), or exclude already-flagged days from the 28-day window, so one spike can't widen the range for the
  next four weeks.
