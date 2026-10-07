# Documentation

Data collection frozen on 2026-10-07; the published snapshot and the hosted dashboard show the final state.

## Reading order

1. [BRD.md](BRD.md): the four business questions, scope and coverage limits.
2. [ANALYTICS.md](ANALYTICS.md): how each figure is computed, and the results.
3. [TRD.md](TRD.md): architecture, technical requirements, known limitations and collection incidents.
4. [PIPELINE.md](PIPELINE.md) and [DATA_MODEL.md](DATA_MODEL.md): how the data flows, and the models it ends up in.
5. [RUNBOOK.md](RUNBOOK.md): explore the results, reproduce the pipeline, operate it.

## Documents

Each topic has one home; other documents link to it.

| Document | Topic |
|---|---|
| [BRD.md](BRD.md) | Business questions, scope, coverage limits, success criteria |
| [TRD.md](TRD.md) | Architecture, technical requirements, known limitations, collection incidents |
| [DATA_SOURCES.md](DATA_SOURCES.md) | Sources, licences, attribution, contents of the public snapshot |
| [PIPELINE.md](PIPELINE.md) | Flows, dbt modes, observability, health rules |
| [DATA_MODEL.md](DATA_MODEL.md) | Layers, models, grains, layer rules, query rules, tests, rows dropped or filtered |
| [ANALYTICS.md](ANALYTICS.md) | Metric definitions, baselines, results |
| [RUNBOOK.md](RUNBOOK.md) | Steps: explore the results without credentials, reproduce, operate, troubleshoot |
| [tests/](tests/) | Test evidence from 2026-09-28 and 2026-09-29, with fingerprints in [tests/fingerprints/](tests/fingerprints/) |

## Test evidence

| Report | What it shows |
|---|---|
| [dedup_audit_2026_09_28.md](tests/dedup_audit_2026_09_28.md) | Every staging model deduplicates to its natural key |
| [idempotency_test_2026_09_28.md](tests/idempotency_test_2026_09_28.md) | A rerun adds no rows and changes no content |
| [daily_flow_2026_09_28.md](tests/daily_flow_2026_09_28.md) | The daily flow, its gate and its fallbacks |
| [new_game_test_2026_09_28.md](tests/new_game_test_2026_09_28.md) | Adding a game takes one seed row |
| [backfill_gap_2026_09_28.md](tests/backfill_gap_2026_09_28.md) | Eight games missing from the 5-minute backfill, and the fix |
| [layer_refactor_2026_09_29.md](tests/layer_refactor_2026_09_29.md) | The layered dbt models leave every mart identical |
| [observability_2026_09_29.md](tests/observability_2026_09_29.md) | Pipeline logging, health models and the failure paths |
| [index_definitions_2026_09_29.md](tests/index_definitions_2026_09_29.md) | Every percentage and index on the dashboard, with SQL and baselines |
| [index_consistency_2026_09_29.md](tests/index_consistency_2026_09_29.md) | One day definition and medians in SQL leave the headline figures unchanged |

Numbers in the test reports are from their own date; the final numbers are in [ANALYTICS.md](ANALYTICS.md#results).
