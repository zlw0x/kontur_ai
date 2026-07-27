# 13. Выбор моделей Codex и экономия лимитов

## 1. Актуальная рекомендуемая линейка

Для Codex с входом через ChatGPT использовать семейство GPT-5.6:

- `gpt-5.6-sol` — наиболее сильная модель для сложной, неоднозначной и дорогой ошибки;
- `gpt-5.6-terra` — основной рабочий баланс качества, скорости и расхода;
- `gpt-5.6-luna` — быстрые формальные, повторяемые и массовые операции.

Старые `gpt-5.2` и `gpt-5.3-codex` не закладывать в проект: они отмечены как deprecated для Codex при входе через ChatGPT.

Минимальная версия CLI для GPT-5.6 — 0.144.0. Worker должен проверять фактически доступные модели командой/интерактивным model listing и поддерживать конфигурацию fallback.

## 2. Рекомендуемый routing

| Агент/стадия | Основная модель | Effort | Fallback | Причина |
|---|---|---:|---|---|
| Input triage | Luna | low | Terra low | Формальная классификация качества |
| OCR/extraction normalization | Luna | medium | Terra medium | Большой объём, структурированный результат |
| Сопоставление видов | Terra | high | Sol high | Требует пространственного рассуждения |
| Geometry hypothesis | Sol | high | Terra xhigh | Самая критичная неоднозначная стадия |
| Clarification questions | Terra | medium | Sol medium | Нужны точные минимальные вопросы |
| Plan generation | Terra | high | Sol high | Планирование feature tree |
| CAD-IR compilation | Terra | medium | Sol medium | Schema и строгие факты |
| JSON recovery/formatting | Luna | low | Terra low | Повторяемая трансформация |
| Static CAD-IR review | Luna | medium | Terra medium | Проверка структуры и ссылок |
| Repair classification | Terra | medium | Sol high | Анализ логов и причин |
| Repair patch | Terra | high | Sol high | Изменение геометрии требует осторожности |
| Final audit | Sol | high | Terra xhigh | Высокая цена пропущенной ошибки |
| Текст статуса пользователю | Luna | low | Terra low | Простое понятное объяснение |

## 3. Практическая политика для Plus

Поскольку пользовательский аккаунт имеет лимиты, по умолчанию:

- 60–75% вызовов Luna;
- 20–35% Terra;
- не более 1–2 вызовов Sol на обычный заказ;
- Sol включать только при неоднозначной геометрии или финальном аудите сложного заказа;
- не использовать `xhigh` автоматически для каждого вызова;
- `medium` — основной effort;
- `high` — пространственное рассуждение и repair;
- `low` — extraction formatting, summaries, schema repair.

## 4. Dynamic escalation

```text
Luna low
  -> schema valid and confidence high: accept
  -> schema invalid or confidence low: Terra medium
  -> geometric contradiction or multiple hypotheses: Sol high
  -> still unresolved: ask user/manual review
```

Не повторять тот же prompt той же моделью без изменения контекста.

## 5. Confidence thresholds

Начальные значения, подлежащие калибровке на fixtures:

- `>= 0.95`: можно принять размер, если нет противоречий;
- `0.80..0.95`: принять только после cross-view consistency check;
- `< 0.80`: вопрос либо более сильная модель;
- `< 0.60`: не передавать как числовой факт.

Модель не должна сама устанавливать финальный confidence policy — policy задаётся кодом.

## 6. Sol budget triggers

Sol разрешён, если выполняется хотя бы одно:

- два или более правдоподобных 3D-варианта;
- конфликт размеров между видами;
- сложный разрез;
- feature graph не выводится однозначно;
- repair после ошибки Terra;
- финальный аудит модели с высокой стоимостью ошибки;
- оператор запросил deep analysis.

## 7. Не использовать Ultra в runtime сервиса

Ultra/subagents полезны при разработке проекта, но не нужны для каждого пользовательского заказа: они увеличивают непредсказуемость расхода и параллелизм. Runtime orchestrator должен явно запускать отдельные стадии сам.

## 8. Конфигурация profiles

Примеры отдельных profile files:

```toml
# ~/.codex/cad-luna.config.toml
model = "gpt-5.6-luna"
model_reasoning_effort = "low"
sandbox_mode = "workspace-write"
approval_policy = "never"
```

```toml
# ~/.codex/cad-terra.config.toml
model = "gpt-5.6-terra"
model_reasoning_effort = "medium"
sandbox_mode = "workspace-write"
approval_policy = "never"
```

```toml
# ~/.codex/cad-sol.config.toml
model = "gpt-5.6-sol"
model_reasoning_effort = "high"
sandbox_mode = "workspace-write"
approval_policy = "never"
```

Worker не должен редактировать глобальный `~/.codex/config.toml`; он передаёт профиль/флаги на конкретный run.

## 9. Разработка самого проекта

Для Codex, который пишет код проекта:

- Sol high: архитектура, COM interop, state machine, security-critical изменения;
- Terra medium/high: обычные backend/frontend features, тесты, refactoring;
- Luna low/medium: документация, типовые DTO, fixtures, schema formatting;
- Sol xhigh: только для трудноуловимых COM deadlock, data loss или security design review.

## 10. Источники актуальности

Проверять перед релизом:

- https://developers.openai.com/codex/models
- https://developers.openai.com/codex/non-interactive-mode
- https://developers.openai.com/codex/config-reference
- https://developers.openai.com/codex/subagents
- https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan
