# CAD AI Service — Resource Accounting and Pricing

**Рекомендуемый путь:** `docs/COST-ACCOUNTING.md`  
**Версия:** 1.0  
**Дата:** 2026-07-27

## 1. Цель

Для каждого заказа рассчитывать:

1. фактическое потребление ресурсов;
2. внутреннюю себестоимость;
3. API-equivalent стоимость AI;
4. коммерческую цену;
5. маржу;
6. число AI/CAD/repair-итераций;
7. причины превышения первоначальной оценки.

Нужно разделять:

- фактический денежный расход;
- распределённую долю подписки ChatGPT/Codex;
- теневую стоимость токенов;
- коммерческую надбавку за сложность и риск.

При входе Codex CLI через пользовательский ChatGPT-аккаунт нет обычного счёта за каждый токен. Поэтому токены измеряются как ресурс, но фактическая AI-себестоимость текущей схемы определяется распределением стоимости подписки и приобретённых credits между заказами.

## 2. Термины

- **Resource event** — неизменяемая запись о ресурсе.
- **AI run** — один запуск `codex exec` для одной роли.
- **CAD attempt** — одна попытка построения модели.
- **Repair iteration** — изменение CAD-IR после ошибки.
- **Pricing profile** — версия ставок и формул.
- **Cost snapshot** — неизменяемый итоговый расчёт заказа.

## 3. Что измерять

### 3.1. AI run

- agent role;
- model;
- reasoning effort;
- fast/standard mode;
- Codex CLI version;
- prompt version;
- input file hashes;
- start/end/wall time;
- exit code;
- input tokens;
- cached input tokens;
- output tokens;
- reasoning tokens, если CLI предоставляет;
- total tokens;
- CLI usage/credit indicator, если доступен;
- schema result;
- attempt number;
- escalation reason.

Парсер usage должен зависеть от версии CLI. Если поле недоступно, сохранять `null`, а не выдумывать значение.

Fallback order:

1. structured CLI usage;
2. final CLI summary;
3. local tokenizer estimate behind feature flag;
4. `unknown`.

Оценочные токены отмечаются `estimated=true`.

### 3.2. Скрипты и процессы

Для image normalization, schema validation, CAD-IR validation, KompasAdapter, STEP/STL validators, preview и upload:

- wall time;
- CPU user/system time;
- peak memory;
- bytes read/written;
- exit code;
- timeout/termination reason;
- retry number.

### 3.3. КОМПАС-3D

- startup duration;
- document creation duration;
- duration каждой feature operation;
- operation count;
- rebuild count;
- failed feature count;
- CAD attempts;
- M3D/STEP/STL export duration;
- cleanup duration;
- forced termination;
- session reuse count;
- peak memory;
- result file sizes.

### 3.4. Iteration counters

```text
analysis_runs
clarification_cycles
planning_runs
cad_ir_generation_runs
schema_repair_runs
cad_build_attempts
cad_feature_failures
geometry_validation_runs
repair_runs
export_attempts
human_review_minutes
```

### 3.5. Общая инфраструктура

- monthly VPS cost allocation;
- storage GB-days;
- backup storage;
- outbound traffic;
- payment commission;
- refunds;
- human support.

## 4. Модель данных

### 4.1. `resource_events`

```sql
CREATE TABLE resource_events (
    id UUID PRIMARY KEY,
    job_id UUID NOT NULL,
    event_key TEXT NOT NULL,
    event_type TEXT NOT NULL,
    stage TEXT NOT NULL,
    attempt_no INTEGER NOT NULL DEFAULT 1,

    agent_role TEXT,
    model TEXT,
    reasoning_effort TEXT,
    service_tier TEXT,

    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    wall_ms BIGINT,
    cpu_user_ms BIGINT,
    cpu_system_ms BIGINT,
    peak_memory_bytes BIGINT,

    input_tokens BIGINT,
    cached_input_tokens BIGINT,
    output_tokens BIGINT,
    reasoning_tokens BIGINT,
    total_tokens BIGINT,
    token_count_estimated BOOLEAN NOT NULL DEFAULT FALSE,

    bytes_read BIGINT,
    bytes_written BIGINT,
    storage_byte_seconds NUMERIC,

    operation_code TEXT,
    operation_count INTEGER,
    exit_code INTEGER,
    success BOOLEAN NOT NULL,
    failure_code TEXT,

    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE(job_id, event_key)
);
```

Пример идемпотентного ключа:

```text
job:{job_id}:cad:attempt:2:operation:extrude:feature_004
```

### 4.2. `pricing_profiles`

```sql
CREATE TABLE pricing_profiles (
    id UUID PRIMARY KEY,
    code TEXT NOT NULL,
    version INTEGER NOT NULL,
    currency TEXT NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to TIMESTAMPTZ,
    config JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(code, version)
);
```

### 4.3. `job_cost_snapshots`

```sql
CREATE TABLE job_cost_snapshots (
    id UUID PRIMARY KEY,
    job_id UUID NOT NULL,
    pricing_profile_id UUID NOT NULL,

    ai_allocated_cost NUMERIC(14,4) NOT NULL,
    ai_shadow_cost NUMERIC(14,4) NOT NULL,
    worker_cost NUMERIC(14,4) NOT NULL,
    cad_license_cost NUMERIC(14,4) NOT NULL,
    vps_cost NUMERIC(14,4) NOT NULL,
    storage_cost NUMERIC(14,4) NOT NULL,
    human_cost NUMERIC(14,4) NOT NULL,
    payment_cost NUMERIC(14,4) NOT NULL,
    resource_cost NUMERIC(14,4) NOT NULL,

    complexity_surcharge NUMERIC(14,4) NOT NULL,
    risk_reserve NUMERIC(14,4) NOT NULL,
    margin_amount NUMERIC(14,4) NOT NULL,
    final_price NUMERIC(14,2) NOT NULL,

    formula_version TEXT NOT NULL,
    breakdown JSONB NOT NULL,
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## 5. AI-себестоимость

Поддерживать два показателя.

### 5.1. Subscription allocation

```text
AI_POOL = monthly_plan_cost + purchased_credits + attributable_fees
```

```text
BASE_TOKENS =
    input_tokens
  + cached_input_tokens * cached_weight
  + output_tokens * output_weight
  + reasoning_tokens * reasoning_weight
```

```text
RUN_UNITS =
    BASE_TOKENS
  * model_weight
  * reasoning_effort_weight
  * service_tier_weight
```

```text
JOB_UNITS = sum(RUN_UNITS for job)
PERIOD_UNITS = sum(RUN_UNITS for completed jobs in period)
AI_ALLOCATED_COST = AI_POOL * JOB_UNITS / PERIOD_UNITS
```

Начальные внутренние weights — конфигурация, а не официальные тарифы:

```yaml
ai_usage_weights:
  cached_token: 0.20
  output_token: 4.00
  reasoning_token: 1.00

  models:
    gpt-5.6-luna: 1.00
    gpt-5.6-terra: 1.35
    gpt-5.6-sol: 1.80

  reasoning:
    low: 0.75
    medium: 1.00
    high: 1.35
    extra_high: 1.70
    max: 2.20

  service_tier:
    standard: 1.00
    fast: 2.50
```

Эти значения калибруются по реальному расходу credits/лимитов. Если reasoning tokens недоступны, их влияние учитывается только через `reasoning_effort_weight`.

Для первого месяца использовать forecast pool. После накопления истории — rolling median последних трёх периодов.

### 5.2. API-equivalent shadow price

```text
AI_SHADOW_COST =
    input_tokens / 1e6 * configured_input_price
  + cached_input_tokens / 1e6 * configured_cached_price
  + output_tokens / 1e6 * configured_output_price
```

Это не фактический счёт, а оценка будущего перехода на API. Цены не хардкодить; хранить в versioned pricing profile.

## 6. Стоимость локального worker

### 6.1. Часовая ставка

```text
WORKER_HOUR_COST =
    electricity_cost_per_hour
  + hardware_amortization_per_hour
  + cad_license_amortization_per_hour
  + maintenance_per_hour
```

Электричество:

```text
electricity_cost_per_hour = average_power_kw * tariff_per_kwh
```

Рекомендуется измерить умной розеткой idle, Codex-only, KOMPAS build и export.

Амортизация ПК:

```text
hardware_amortization_per_hour =
  replacement_cost / expected_billable_lifetime_hours
```

Лицензия КОМПАС:

```text
cad_license_amortization_per_hour =
  annual_license_cost / planned_productive_hours_per_year
```

### 6.2. Стоимость заказа

```text
WORKER_COST = active_worker_seconds / 3600 * WORKER_HOUR_COST
```

Включаются image processing, Codex CLI wall time, KOMPAS build, validation, export и packaging.

Не включаются ожидание ответа пользователя и время в очереди.

## 7. VPS и storage

На старте:

```text
VPS_COST_PER_JOB = monthly_vps_cost / forecast_completed_jobs
```

После появления нагрузки можно перейти к CPU/storage allocation.

```text
STORAGE_COST =
    source_gb_days * source_rate
  + result_gb_days * result_rate
  + backup_gb_days * backup_rate
  + egress_gb * egress_rate
```

## 8. Итоговая себестоимость и цена

### 8.1. Resource cost

```text
RESOURCE_COST =
    AI_ALLOCATED_COST
  + WORKER_COST
  + CAD_LICENSE_COST
  + VPS_COST
  + STORAGE_COST
  + HUMAN_COST
  + PAYMENT_DIRECT_COST
```

Не включать отдельную плату за итерации в resource cost, если время и токены этих итераций уже учтены. Иначе будет двойной учёт.

### 8.2. Complexity surcharge

Итерации учитываются в коммерческой надбавке за риск:

```text
COMPLEXITY_SURCHARGE =
    max(0, analysis_runs - included_analysis_runs) * analysis_retry_fee
  + max(0, cad_build_attempts - included_cad_attempts) * cad_retry_fee
  + max(0, repair_runs - included_repair_runs) * repair_fee
  + advanced_feature_points * feature_point_price
```

### 8.3. Risk reserve

```text
RISK_RESERVE = RESOURCE_COST * risk_percent_by_class
```

Пример конфигурации:

```yaml
risk:
  AUTO_SIMPLE: 0.05
  AUTO_STANDARD: 0.10
  AUTO_ADVANCED: 0.20
  MANUAL_REVIEW: 0.15
```

### 8.4. Final price

```text
PRE_MARGIN = RESOURCE_COST + COMPLEXITY_SURCHARGE + RISK_RESERVE
```

```text
FINAL_PRICE = round_to_step(
  max(
    minimum_price_for_class,
    PRE_MARGIN / (1 - target_gross_margin)
  )
)
```

При target margin 60% делитель равен 0.40.

## 9. Feature complexity points

Points нужны для предварительной оценки и minimum price, но не заменяют resource ledger.

| Feature | Points |
|---|---:|
| Sketch primitive | 0.1 |
| Constraint/dimension | 0.1 |
| Extrude/Revolve | 1 |
| Simple hole | 0.25 |
| Complex hole | 0.75 |
| Fillet/Chamfer group | 0.5 |
| Pattern | 1 |
| Boolean | 1 |
| Shell | 2 |
| Rib/Draft | 1.5 |
| Modeled thread | 3 |
| Sweep | 3 |
| Loft | 4 |
| Surface operation | 5 |
| Sheet-metal bend | 2 |
| Assembly mate | 1 |

После 500 заказов веса пересчитать по wall time, failure rate, repairs, refunds и human minutes.

## 10. Предварительная и финальная цена

### До выполнения

После дешёвого analysis pass показать:

- class;
- price range;
- hard cap;
- included repairs;
- unsupported risks.

```json
{
  "class": "AUTO_STANDARD",
  "price_min_rub": 290,
  "price_max_rub": 690,
  "included_repairs": 2,
  "hard_cap_rub": 690
}
```

Числа — пример интерфейса, не готовый прайс.

### Во время выполнения

Если predicted final price превышает hard cap:

- pause job;
- запросить согласие;
- не запускать дорогой Sol/surface/CAD attempt автоматически.

### После выполнения

Пользователю показывать понятный breakdown:

- базовая обработка;
- сложность модели;
- дополнительные итерации;
- расширенные features;
- итог.

В админке — полный breakdown по токенам, моделям, времени, attempts, storage и margin.

## 11. Budget guard

```yaml
budget:
  max_total_tokens: 300000
  max_sol_tokens: 80000
  max_ai_runs: 8
  max_clarification_cycles: 3
  max_cad_attempts: 4
  max_repairs: 2
  max_worker_wall_seconds: 1800
  max_human_minutes: 0
  max_internal_cost_rub: 500
```

Проверять budget:

- перед каждым AI run;
- перед Sol escalation;
- перед CAD attempt;
- перед surface/sheet-metal path;
- после каждого recalculation.

## 12. Дашборды и алерты

### По заказу

- resource cost;
- final price/margin;
- tokens by model;
- AI runs;
- CAD attempts;
- worker wall time;
- operation timings;
- quality score.

### По месяцу

- completed jobs;
- median/P95 cost;
- average tokens;
- subscription pool usage;
- failure/repair rate;
- expensive features;
- margin by tariff;
- worker utilization;
- refunds.

### Alerts

- cost above threshold;
- Sol usage above budget;
- repair spike;
- leaked process;
- unknown CLI version;
- token parser failure;
- negative margin;
- storage growth.

## 13. Acceptance criteria

- duplicate event не удваивает стоимость;
- restart/retry не теряет events;
- pricing profile immutable;
- одинаковые ledger/profile дают одинаковый результат;
- token fields nullable;
- estimated tokens помечены;
- final snapshot содержит formula version;
- ожидание пользователя не увеличивает worker cost;
- retries видны отдельно;
- нет двойного учёта iterations;
- completed snapshot неизменяем;
- заказ воспроизводим по hashes, versions и CAD-IR.

## 14. Порядок внедрения

1. resource contracts;
2. DB migration;
3. worker process instrumentation;
4. Codex usage adapter;
5. KOMPAS operation timers;
6. pure cost engine;
7. pricing profiles;
8. budget guard;
9. admin breakdown;
10. user estimate;
11. payment integration;
12. calibration after 100 and 500 jobs.
