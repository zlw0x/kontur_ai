# Prompt for Codex — Start Post-MVP Phase

Работай в существующем репозитории CAD AI Service. Текущий вертикальный MVP подтверждён реальным E2E: PNG/JPEG → Codex CLI → CAD-IR → КОМПАС-3D → M3D/STEP/STL. Поддерживаются прямоугольная призма и до 19 круглых сквозных отверстий.

Перед изменениями прочитай:

- `README.md`
- `AGENTS.md`
- `docs/MVP-RUNBOOK.md`
- `docs/TASK-011-014-mvp-drawing-web.md`
- `docs/adr/ADR-014-bounded-drawing-mvp.md`
- `docs/POST-MVP-ROADMAP.md`
- `docs/COST-ACCOUNTING.md`

## Цель этой сессии

Реализовать только фундамент Post-MVP:

1. append-only resource ledger;
2. versioned pricing profiles;
3. deterministic job cost calculator;
4. capability registry;
5. instrumentation существующего prism/hole pipeline;
6. tests и документацию.

Не добавляй новые операции КОМПАС в этой сессии.

## Ограничения

- Не переписывай рабочий MVP без необходимости.
- Не меняй подтверждённый CAD scope.
- Не добавляй OpenAI API key.
- Codex CLI продолжает использовать локальную пользовательскую авторизацию.
- Не исполняй произвольный код, сгенерированный моделью.
- Не ослабляй sandbox/security.
- Не хардкодь цены, weights, тариф электричества или лицензию.
- Все ставки находятся в versioned pricing profile.
- Все write operations идемпотентны.
- Существующие leases/recovery/idempotency сохраняются.
- Completed cost snapshot immutable.
- Nullable token metrics допустимы.
- Не выдумывай usage, если CLI его не предоставляет.
- Делай небольшие логические изменения с тестами.

## 1. Contracts

Добавь DTO/JSON Schema:

- `ResourceEvent`;
- `AiUsage`;
- `ProcessUsage`;
- `CadUsage`;
- `JobIterationCounters`;
- `PricingProfile`;
- `JobCostBreakdown`;
- `JobCostSnapshot`;
- `WorkerCapabilityManifest`.

Используй stable string enums и schema version.

## 2. Database

Добавь migrations:

- `resource_events`;
- `pricing_profiles`;
- `job_cost_snapshots`;
- при необходимости `worker_capability_snapshots`.

Требования:

- UUID PK;
- `UNIQUE(job_id, event_key)`;
- JSONB metadata;
- TIMESTAMPTZ;
- indexes по `job_id`, `event_type`, `started_at`;
- immutable completed snapshot на service layer и в tests.

## 3. Resource ingestion

Добавь worker-authenticated API/service для batch записи events.

Обеспечь:

- idempotency;
- validation;
- rejection negative counters;
- retry после network interruption;
- event key collision handling;
- audit log.

## 4. Worker instrumentation

Инструментируй текущие стадии:

- image preprocessing;
- каждый Codex CLI run;
- JSON Schema validation;
- semantic CAD-IR validation;
- KOMPAS startup;
- document build;
- rectangular prism operation;
- each hole operation;
- rebuild;
- M3D/STEP/STL export;
- geometry validation;
- preview generation;
- artifact upload;
- cleanup.

Записывай wall time, process CPU time и peak memory где возможно, exit code, bytes, attempts и typed failure code.

## 5. Codex usage adapter

Создай version-aware interface:

```text
ICodexUsageParser
  CanParse(cliVersion, outputFormat)
  Parse(output)
```

Требования:

- structured output first;
- summary fallback;
- tokenizer estimate только за feature flag;
- `estimated=true`;
- неизвестные fields остаются null;
- fixtures для известных CLI outputs;
- unknown CLI version не ломает заказ, но создаёт warning event;
- domain code не зависит от строк stdout.

## 6. Cost engine

Реализуй pure deterministic function:

```text
CalculateCost(resourceEvents, pricingProfile) -> JobCostBreakdown
```

Поддержи:

- subscription allocation inputs;
- API-equivalent shadow price;
- worker hourly cost;
- VPS/storage allocation;
- CAD license allocation;
- human review;
- payment fee;
- complexity surcharge;
- risk reserve;
- target margin;
- minimum price;
- rounding step.

Pure function не использует global config, current time или database.

## 7. Capability registry

Зарегистрируй текущие capabilities:

- `solid.rectangular_prism`;
- `feature.hole.simple_through`;
- `export.m3d`;
- `export.step`;
- `export.stl`;
- `validate.manifold`;
- `validate.bounding_box`;
- `validate.hole_count`.

Worker публикует manifest. API проверяет compatibility до lease.

## 8. Tests

Обязательные tests:

- duplicate resource event;
- restart/retry ingestion;
- invalid negative token count;
- nullable tokens;
- deterministic cost;
- immutable completed snapshot;
- pricing profile versioning;
- recalculation draft с другим profile;
- existing E2E emits resource events;
- capability mismatch prevents lease;
- unknown CLI version warning;
- process failure event;
- no double counting retries.

Запусти:

- Python tests;
- PostgreSQL integration;
- .NET tests;
- web typecheck/build;
- schema validation;
- Docker Compose smoke test;
- real KOMPAS E2E только если среда и лицензия доступны.

## 9. Documentation

Создай:

- `docs/TASK-POSTMVP-001-RESOURCE-LEDGER.md`;
- `docs/TASK-POSTMVP-002-COST-ENGINE.md`;
- ADR по subscription allocation и API shadow pricing;
- migration/runbook notes;
- example pricing profile без реальных секретов.

## Финальный отчёт

Укажи:

- изменённые файлы;
- migrations;
- формулы;
- какие metrics CLI реально доступны;
- какие fields nullable;
- tests;
- risks;
- следующий рекомендуемый task.

Не переходи к revolve, fillet, chamfer или другим новым CAD operations в этой сессии.
