# 11. Тестирование и приёмка

## 1. Test pyramid

### Unit tests

- state transitions;
- CAD-IR schema;
- expression evaluator;
- feature graph;
- semantic selectors;
- API authorization;
- retry/backoff;
- JSONL parser Codex;
- error mapping КОМПАС.

### Integration tests

- PostgreSQL + API;
- S3 upload/finalize;
- worker claim/lease;
- Codex CLI stub;
- KOMPAS adapter на реальной машине;
- export + mesh validator.

### End-to-end

- browser -> VPS -> local worker -> result;
- question round trip;
- repair loop;
- worker disconnect;
- duplicate message;
- expired signed URL.

## 2. Test modes

### Fake AI

Возвращает fixture JSON. Используется в CI.

### Fake CAD

Создаёт заранее подготовленные artifacts и ошибки. Используется на Linux CI.

### Real Codex

Запускается вручную/по расписанию на доверенной машине с budget cap.

### Real KOMPAS

Запускается на Windows CAD test machine. Не нужен для каждого commit, но обязателен перед release.

## 3. Drawing fixture classes

1. Простая пластина с четырьмя отверстиями.
2. Ступенчатый вал.
3. Втулка.
4. Фланец с круговым массивом.
5. L-кронштейн.
6. Корпус с крышкой как одна деталь без сборки.
7. Деталь с разрезом.
8. Деталь с фасками.
9. Деталь со скруглениями.
10. Неоднозначное несквозное отверстие.
11. Противоречивые размеры.
12. Плохое качество изображения.
13. Prompt injection в примечании.
14. Дюймовые размеры — ожидаемый отказ/уточнение MVP.
15. Несколько деталей на листе — ожидаемое уточнение.

## 4. Metrics

### Extraction

- dimension precision/recall;
- view detection accuracy;
- feature identification accuracy;
- calibration confidence.

### CAD

- build success rate;
- exact parameter match;
- invariant pass rate;
- mesh validity;
- number of repair attempts.

### Product

- доля заказов без ручной проверки;
- среднее число вопросов;
- отказ по плохому входу;
- время ожидания worker;
- число повторных построений;
- пользовательские возвраты.

### AI usage

- runs per stage;
- model distribution;
- reasoning effort distribution;
- usage reported Codex;
- limit/rate errors;
- percentage Luna/Terra/Sol.

## 5. Acceptance gate по этапам

### CAD builder gate

- 20/20 fixtures build;
- no orphan KOMPAS process;
- deterministic geometry fingerprint;
- explicit errors.

### VPS gate

- auth tests;
- ownership tests;
- lease tests;
- file integrity tests;
- state machine coverage.

### AI gate

- 50 drawing fixtures;
- no invalid schema reaches builder;
- uncertain dimensions trigger questions;
- injection tests pass.

### Pilot gate

- manual approval enabled;
- rollback tested;
- backups tested;
- alerts configured;
- legal and license questions reviewed.

## 6. Regression dataset

Каждая реальная ошибка после удаления персональных данных превращается в regression fixture, если пользователь дал согласие на такое использование. Fixture должен содержать минимально необходимый фрагмент, ожидаемый результат и причину прежней ошибки.

## 7. Release checklist

- migrations tested;
- frontend/backend contracts generated;
- worker protocol backward compatible;
- schema version supported;
- KOMPAS probe green;
- Codex probe green;
- secret scan green;
- dependency scan reviewed;
- backup restore test successful;
- rollback package available.
