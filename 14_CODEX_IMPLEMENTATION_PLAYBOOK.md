# 14. Инструкция Codex для воплощения проекта

## 1. Как давать проект Codex

Открыть корень monorepo в Codex CLI/приложении. В корне должны находиться:

- `AGENTS.md`;
- этот комплект ТЗ в `/docs`;
- issue/task files;
- fixture data;
- актуальный журнал решений `docs/adr/`.

## 2. Обязательная последовательность работы

Codex должен:

1. Прочитать `AGENTS.md`.
2. Прочитать документацию конкретного этапа.
3. Исследовать существующий код и тесты.
4. Сформировать короткий implementation plan.
5. Реализовать только текущий milestone.
6. Запустить format, lint, typecheck и tests.
7. Исправить ошибки.
8. Проверить git diff.
9. Обновить документацию и changelog.
10. Вернуть summary, tests и known limitations.

## 3. Не разрешать Codex

- сразу реализовывать все этапы;
- менять архитектурные решения без ADR;
- добавлять прямой OpenAI API;
- переносить Codex auth на VPS;
- выполнять КОМПАС через UI-клики как основной метод;
- запускать произвольный AI-generated code;
- пропускать tests;
- скрывать TODO критического пути;
- придумывать API КОМПАС без проверки type library/SDK на локальном ПК.

## 4. Definition of done для задачи

- код компилируется;
- тесты проходят;
- ошибки типизированы;
- есть logs/metrics;
- нет секретов;
- обновлены contracts;
- миграции обратимы либо описан rollback;
- документация соответствует реализации;
- ручная проверка указана там, где автоматическая невозможна.

## 5. Первые задачи для Codex

### TASK-001 Repository bootstrap

Создать monorepo, базовые приложения, linting, formatting, test runners, Docker Compose dev environment и CI без реального КОМПАС.

### TASK-002 Contracts

Создать OpenAPI contracts, worker job DTO, state enums, error codes, JSON schemas и generated TypeScript client.

### TASK-003 Order state machine

Реализовать state transitions и tests всех разрешённых/запрещённых переходов.

### TASK-004 Worker claim protocol

Реализовать registration, heartbeat, claim, lease renewal, completion и idempotency.

### TASK-005 Local worker skeleton

Создать .NET worker CLI, config, DPAPI credential store, polling loop, workspace lifecycle и fake job handler.

### TASK-006 Kompas probe

На локальном Windows-ПК исследовать installed SDK/type libraries и создать реальный probe. Не писать adapter до подтверждения рабочего минимального API path.

### TASK-007 CAD-IR validator

Реализовать schema validation, feature graph, parameter evaluator и fixtures.

### TASK-008 Kompas adapter v0

Реализовать rectangle sketch, extrude, circle, cut/hole, save, STEP, STL.

### TASK-009 End-to-end manual CAD-IR

Связать web order с локальной сборкой вручную подготовленного CAD-IR.

### TASK-010 Codex runner

Реализовать безопасный wrapper `codex exec`, JSONL parser, output schema, model routing, timeout и limit errors.

Только после TASK-010 переходить к drawing analysis.

## 6. Шаблон задачи для Codex

```text
Цель:
Реализовать TASK-XXX строго в рамках milestone N.

Прочитай:
- AGENTS.md
- docs/...

Входные ограничения:
- не менять архитектуру;
- не использовать прямой OpenAI API;
- не трогать секреты;
- не добавлять новые зависимости без обоснования.

Требуемый результат:
- перечислить конкретные files/modules;
- реализовать production-quality код;
- добавить tests;
- обновить docs;
- запустить проверки.

Критерии приёмки:
...

В конце сообщи:
- что изменено;
- какие команды проверки выполнены;
- какие ограничения остались;
- какие решения требуют моего участия.
```

## 7. Разбиение PR

Один PR/commit series — один bounded change. Не смешивать:

- backend schema и большой frontend redesign;
- KOMPAS interop и billing;
- security refactor и visual polish.

## 8. Использование агентов при разработке

- `architect`: читает ТЗ и проверяет границы.
- `backend_worker`: реализует FastAPI/PostgreSQL.
- `windows_cad`: работает с .NET/COM/КОМПАС.
- `contract_reviewer`: проверяет JSON/OpenAPI совместимость.
- `test_reviewer`: ищет недостающие failure tests.
- `security_reviewer`: проверяет trust boundaries.

Parent agent обязан собрать результаты и сам проверить diff. Subagent findings не считаются истинными без evidence в коде/tests.

## 9. Stop and ask policy для Codex-разработчика

Codex должен остановиться и запросить решение владельца только когда:

- требуется выбрать конкретную лицензионную схему КОМПАС;
- установленная версия SDK не соответствует документации;
- API не позволяет требуемую операцию;
- изменение затрагивает удаление пользовательских данных;
- нужен production secret/domain/payment provider;
- два архитектурных варианта имеют существенно разные trade-offs.

В остальных случаях Codex выбирает консервативный вариант, документирует его в ADR и продолжает.
