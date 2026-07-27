# 06. Оркестрация Codex CLI

## 1. Основное решение

Проект не вызывает OpenAI API напрямую. Все AI-стадии запускаются локально через `codex exec`, авторизованный пользовательским ChatGPT-аккаунтом.

Пример базового вызова:

```powershell
codex --ask-for-approval never exec `
  --ephemeral `
  --json `
  --sandbox workspace-write `
  --model gpt-5.6-terra `
  --image .\input\page-001.png `
  --config model_reasoning_effort='"medium"' `
  --output-schema .\schemas\drawing-analysis.schema.json `
  --output-last-message .\output\drawing-analysis.json `
  "Выполни задачу из prompts/stage.md. Работай только в текущей папке."
```

`--image/-i` прикрепляет PNG/JPEG к исходному prompt; для нескольких страниц флаг повторяется или пути перечисляются через запятую. Фактические флаги проверять через `codex exec --help` установленной версии. Wrapper должен выполнять version/capability detection, а не предполагать наличие флага.

## 2. Почему отдельные вызовы, а не один длинный разговор

- Явные границы стадий.
- Отдельные JSON Schema.
- Проще повторять неудачную стадию.
- Контролируемое потребление контекста.
- Можно использовать разные модели и reasoning effort.
- Меньше риск, что repair agent изменит пользовательские факты.

## 3. Стадии AI pipeline

### A. Input triage

Вход: нормализованные изображения и manifest.

Выход:

- пригодность;
- ориентация;
- предполагаемые единицы;
- количество видов;
- критические проблемы качества.

### B. Drawing extraction

Вход: изображения.

Выход:

- виды;
- размерные надписи;
- геометрические примитивы;
- предполагаемые связи;
- confidence;
- bounding boxes источников.

### C. Geometry reasoning

Вход: extraction JSON + изображения.

Выход:

- feature graph;
- несколько гипотез при неоднозначности;
- отсутствующие данные;
- вопросы.

### D. Clarification synthesis

Вход: hypotheses + история ответов.

Выход: минимальный набор вопросов, который максимально уменьшает неопределённость.

### E. CAD planning

Вход: подтверждённые факты.

Выход: порядок CAD-операций и ожидаемые инварианты.

### F. CAD-IR compilation

Вход: план и факты.

Выход: CAD-IR строго по schema.

### G. Repair

Вход: CAD-IR, validator report, КОМПАС logs.

Выход: JSON Patch либо новый CAD-IR с объяснением изменённых feature IDs.

### H. Audit

Вход: исходный drawing analysis, окончательный CAD-IR, validation report, рендеры.

Выход: `pass`, `manual_review` или `fail` с конкретными причинами.

## 4. Контекст задания

Codex получает только:

```text
context/
  order-summary.json
  input-manifest.json
  user-answers.json
  prior-stage-output.json
  cad-operation-catalog.md
  cad-ir.schema.json
  stage-instructions.md
input/
  page-001.png
```

Не передавать:

- конфигурацию VPS;
- worker token;
- Codex auth;
- чужие заказы;
- домашние каталоги;
- исходный код всего worker, если стадия занимается только анализом чертежа.

## 5. Structured output

Каждый AI-run должен иметь schema. Если output невалиден:

1. Попытаться извлечь final message.
2. Выполнить локальную schema validation.
3. Один раз запустить formatter/recovery агент на Luna.
4. Если не помогло — повторить исходную стадию на Terra или Sol.
5. После лимита попыток — manual review.

## 6. Обработка JSONL

Wrapper сохраняет весь `--json` stream в `logs/codex-events.jsonl` и извлекает:

- thread ID;
- статус turn;
- usage;
- command execution;
- file changes;
- final message;
- error event.

В backend отправляется только очищенная сводка. Полный лог остаётся локально до истечения retention.

## 7. Resume

Использовать `codex exec resume` только для этапа уточнений, когда продолжение той же логической нити действительно уменьшает повторную передачу контекста. Для CAD compilation и repair предпочтительнее новые ephemeral runs с полным структурированным контекстом.

Нельзя полагаться исключительно на resume ID: pipeline должен уметь продолжить из сохранённых JSON после потери Codex thread.

## 8. Ограничение лимитов

Worker поддерживает budget policy:

```json
{
  "max_ai_runs_per_order": 10,
  "max_sol_runs_per_order": 2,
  "max_repair_runs": 3,
  "max_question_rounds": 3,
  "fallback_on_limit": "WAIT_FOR_CAPACITY"
}
```

При rate limit:

- не считать заказ failed;
- установить `WAITING_FOR_AI_CAPACITY`;
- сохранить `retry_after`, если доступно;
- не выполнять частые повторные запросы;
- позволить оператору выбрать другую доступную модель.

## 9. Approval и sandbox

В AI pipeline Codex нужен доступ только к workspace конкретного задания. Он не должен напрямую запускать КОМПАС. Вместо этого Codex формирует JSON, а доверенный worker вызывает KompasAdapter.

Это принципиальная граница:

```text
Codex -> JSON Schema -> Validator -> trusted adapter -> КОМПАС
```

Не использовать:

```text
Codex -> сгенерированный PowerShell/Python -> unrestricted execution
```

## 10. Кэширование контекста на уровне приложения

Так как используется CLI и пользовательский аккаунт, backend не управляет API prompt cache. Экономия достигается иначе:

- короткие stage prompts;
- отдельные компактные JSON;
- отсутствие повторной отправки нерелевантных файлов;
- модели Luna/Terra для формальных стадий;
- hash результата стадии;
- повторное использование extraction при пользовательской правке, не затрагивающей изображение;
- детерминированный code path без LLM там, где это возможно.
