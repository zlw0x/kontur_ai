# 18. Первый промпт для Codex

Скопируй этот текст в Codex, открыв корень нового репозитория проекта.

```text
Ты ведущий инженер проекта CAD AI Service.

Цель проекта: внешний веб-сервис на VPS принимает технический чертёж, локальный Windows-worker анализирует его через Codex CLI, задаёт пользователю уточняющие вопросы, формирует CAD-IR, строит модель через КОМПАС-3D API и возвращает STL/STEP/M3D.

Критические ограничения:
- AI вызывается только локально через Codex CLI, авторизованный моим ChatGPT-аккаунтом; прямой OpenAI API запрещён.
- Codex auth и лицензия КОМПАС не покидают локальный ПК.
- VPS не имеет remote shell к локальному ПК.
- Локальный worker сам делает исходящие HTTPS-запросы к VPS.
- AI не генерирует исполняемый CAD-скрипт для непосредственного запуска. Он создаёт JSON по schema, затем доверенный KompasAdapter выполняет операции.
- Не придумывай методы КОМПАС API: сначала исследуй установленный SDK/type libraries и создай probe.
- Не используй UI automation КОМПАС как основной путь.

Сначала прочитай:
1. AGENTS.md
2. 00_README.md
3. 01_PRODUCT_REQUIREMENTS.md
4. 02_ARCHITECTURE.md
5. 03_ROADMAP.md
6. 14_CODEX_IMPLEMENTATION_PLAYBOOK.md
7. остальные документы по ссылкам из README.

Текущая задача — только TASK-001 Repository bootstrap и подготовка TASK-002 Contracts. Не реализуй vision, Codex runtime и КОМПАС adapter на этом шаге.

Сделай следующее:
1. Исследуй пустой/текущий репозиторий.
2. Предложи точную структуру monorepo, соответствующую ТЗ.
3. Создай apps/web, apps/api, apps/local-worker и packages/contracts, packages/cad-ir, packages/kompas-adapter, packages/geometry-validation.
4. Настрой локальную разработку VPS-компонентов через Docker Compose: PostgreSQL, Redis, MinIO, API и web.
5. Для backend создай FastAPI skeleton, settings validation, health endpoint, structured logging и pytest.
6. Для frontend создай Next.js/TypeScript skeleton, API client boundary и минимальную health page.
7. Для local-worker создай .NET solution с console host, config validation и fake job handler; код должен собираться без КОМПАС.
8. Добавь OpenAPI/JSON Schema directories и механизм генерации/проверки contracts.
9. Добавь CI, который запускает format, lint, typecheck, unit tests и build без реального Codex/КОМПАС.
10. Добавь .gitignore, .editorconfig, README для разработки и безопасные env examples без секретов.
11. Не меняй документы ТЗ, кроме явных исправлений ссылок/структуры; архитектурные изменения оформляй ADR.
12. Выполни все проверки и исправь ошибки.

Критерии приёмки:
- monorepo собирается с чистого checkout;
- docker compose поднимает dev dependencies;
- API и web health доступны;
- local-worker fake mode запускается;
- тесты не требуют пользовательской Codex auth и КОМПАС;
- секретов в репозитории нет;
- direct OpenAI API dependencies отсутствуют.

Перед изменениями дай короткий план. После реализации сообщи:
- созданные компоненты;
- команды запуска;
- выполненные проверки;
- список оставшихся задач TASK-002;
- все решения, которые требуют моего участия.
```

## Следующий промпт после bootstrap

```text
Реализуй TASK-002 Contracts и TASK-003 Order state machine.
Прочитай AGENTS.md, 01_PRODUCT_REQUIREMENTS.md, 04_VPS_BACKEND.md, 07_CAD_IR.md и 16_API_PROTOCOL.md.

Нужны:
- versioned OpenAPI contracts;
- order/job/worker DTO;
- enums и typed error codes;
- CAD-IR schema package;
- worker protocol versioning;
- state machine с таблицей разрешённых переходов;
- optimistic locking;
- unit tests всех разрешённых и запрещённых переходов;
- generated TypeScript client;
- backward-compatibility checks.

Не реализуй реальный CodexRunner и KompasAdapter.
В конце запусти все проверки, покажи summary и перечисли contract decisions.
```
