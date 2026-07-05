# Profile Theme Persona Rescore Comparison

- smoke_dir: `docs\tasks\results\v2_retrieval_smoke\20260630T094517`
- scoring: active theme weights normalized; single-theme requests are invariant.

## Grid Summary Top Churn

| config | personas_with_any_change | max_changed | avg_changed |
|---|---:|---:|---:|
| alpha=2.0\|range=strong\|cap=0.03 | 9 | 3 | 0.7 |
| alpha=2.0\|range=strong\|cap=0.05 | 9 | 3 | 0.7 |
| alpha=2.0\|range=strong\|cap=0.08 | 9 | 3 | 0.7 |
| alpha=2.0\|range=medium\|cap=0.03 | 8 | 2 | 0.6 |
| alpha=2.0\|range=medium\|cap=0.05 | 8 | 2 | 0.6 |

## Representative Config

`alpha=1.5|range=medium|cap=0.05`

- changed personas: 7/20
- max changed cases/persona: 2

| persona | changed | examples |
|---|---:|---|
| P00_new_user_uniform | 0 | - |
| P01_one_trip_sea_probe | 0 | - |
| P02_one_trip_healing_probe | 0 | - |
| P03_two_trips_repeated_sea | 0 | - |
| P04_two_trips_split_sea_healing | 0 | - |
| P05_three_trips_sea_threshold | 1 | 009_v1dump_10_coast_healing_daytrip_daegu CITY#YEONGDEOK->CITY#GUNSAN |
| P06_three_trips_nature_threshold | 0 | - |
| P07_three_trips_balanced_three_themes | 2 | 009_v1dump_10_coast_healing_daytrip_daegu CITY#YEONGDEOK->CITY#GUNSAN, 014_v1dump_15_wrapped_agentcore_history_art_2d1n CITY#JEONJU->CITY#ANDONG |
| P08_three_trips_multi_theme_even | 0 | - |
| P09_five_trips_sea_lover | 1 | 009_v1dump_10_coast_healing_daytrip_daegu CITY#YEONGDEOK->CITY#GUNSAN |
| P10_five_trips_history_culture | 2 | 014_v1dump_15_wrapped_agentcore_history_art_2d1n CITY#JEONJU->CITY#ANDONG, 030_v2mock_08_history_nature_2d1n_userloc CITY#BUK-GWANGJU->CITY#JEJU |
| P11_five_trips_art_sense | 2 | 014_v1dump_15_wrapped_agentcore_history_art_2d1n CITY#JEONJU->CITY#JONGNO-GU, 101_pair_coast_art CITY#JINDO->CITY#SEOGWIPO |
| P12_five_trips_healing_rest | 0 | - |
| P13_five_trips_sea_healing | 0 | - |
| P14_five_trips_nature_history | 1 | 014_v1dump_15_wrapped_agentcore_history_art_2d1n CITY#JEONJU->CITY#ANDONG |
| P15_five_trips_uniform | 0 | - |
| P16_ten_trips_sea_healing_mature | 0 | - |
| P17_ten_trips_nature_history_mature | 0 | - |
| P18_ten_trips_art_history_mature | 1 | 101_pair_coast_art CITY#JINDO->CITY#SEOGWIPO |
| P19_ten_trips_uniform_mature | 0 | - |
