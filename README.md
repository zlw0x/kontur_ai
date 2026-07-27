# CAD AI Service

Готовый вертикальный MVP безопасного конвейера «чертёж → проверенная
3D-модель». Публичные API и web работают в Docker, а Codex CLI и
КОМПАС-3D запускаются только локальным Windows worker на доверенном ПК.

## Возможности MVP

- загрузка PNG/JPEG через web;
- локальный анализ чертежа через авторизацию Codex CLI без OpenAI API key;
- цикл уточняющих вопросов по неуверенным размерам;
- строгие JSON Schema и typed CAD-IR перед обращением к КОМПАС;
- детерминированное построение прямоугольной пластины с круглыми сквозными
  отверстиями;
- сохранение M3D и экспорт STEP/STL;
- независимая проверка STL: manifold, число тел, габариты и число сквозных
  отверстий;
- браузерное 3D-превью и скачивание артефактов;
- outbound-only worker, lease/idempotency, SHA-256 и DPAPI credential.

Текущая подтверждённая геометрическая область — одна прямоугольная призма и
до 19 круглых сквозных отверстий. Другие операции отклоняются typed-ошибкой;
это не универсальное восстановление произвольных деталей.

## Запуск VPS-части

```powershell
Copy-Item .env.example .env
# Перед внешним развёртыванием замените все значения *change-me.
docker compose --env-file .env -f infra/docker-compose.yml up -d --build
```

Проверки:

- web: `http://localhost:3000`;
- API: `http://localhost:8000/health`;
- в поле токена web используется `MANUAL_API_TOKEN` из `.env`.

## Подключение локального worker

На доверенном Windows ПК должны быть установлены .NET 8 SDK, Codex CLI с
локальной ChatGPT-авторизацией и КОМПАС-3D v22 x64.

```powershell
dotnet run --project apps/local-worker/CadAi.LocalWorker.csproj -- probe-codex
dotnet run --project apps/local-worker/CadAi.LocalWorker.csproj -- probe-kompas
dotnet run --project apps/local-worker/CadAi.LocalWorker.csproj -- enroll `
  --server http://localhost:8000 `
  --token <WORKER_ENROLLMENT_TOKEN>
dotnet run --project apps/local-worker/CadAi.LocalWorker.csproj -- run
```

Worker сам инициирует все соединения. Credential сохраняется через Windows
DPAPI в `%LOCALAPPDATA%\CadAiWorker`; Codex auth и лицензия КОМПАС не
передаются API.

Подробные команды эксплуатации находятся в
[`docs/MVP-RUNBOOK.md`](docs/MVP-RUNBOOK.md), а доказательства приёмки — в
[`docs/TASK-011-014-mvp-drawing-web.md`](docs/TASK-011-014-mvp-drawing-web.md).

## Post-MVP: учёт ресурсов и реестр возможностей

Геометрическая область не расширена. Добавлен фундамент, без которого нельзя
считать себестоимость и безопасно добавлять операции:

- append-only журнал ресурсов задания с идемпотентным приёмом событий;
- детерминированный расчёт стоимости по версионированному pricing profile;
- неизменяемый итоговый cost snapshot;
- реестр возможностей: API не выдаёт worker'у задание, операции которого тот
  не умеет строить.

Все денежные ставки в `examples/pricing-profile.example.json` равны нулю —
их нужно измерить на реальной машине, а не брать из примера. Подробности:
[`docs/TASK-POSTMVP-001-RESOURCE-LEDGER.md`](docs/TASK-POSTMVP-001-RESOURCE-LEDGER.md),
[`docs/TASK-POSTMVP-002-COST-ENGINE.md`](docs/TASK-POSTMVP-002-COST-ENGINE.md),
[`docs/POST-MVP-ROADMAP.md`](docs/POST-MVP-ROADMAP.md).

