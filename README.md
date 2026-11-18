# CAD AI Service

Kontur — веб-сервис «чертёж → проверенная 3D-модель → параметрические правки».
Web и API работают в Docker. Анализ изображения выполняет локально
авторизованный Codex CLI; CAD выполняет build123d/OpenCascade через доверенный
worker. KOMPAS, COM, M3D и лицензирование CAD удалены из рабочего конвейера.

Коммерческий релиз ещё не завершён. Текущий приоритет — сохранённые проекты и
последовательное редактирование: [план Kontur 1.0](docs/KONTUR-1.0-RELEASE-PLAN.md),
[устройство редактора](docs/adr/ADR-042-a-project-is-an-immutable-sequence-of-documents.md).
Подтверждённый сценарий и ограничения: [приёмка этапа 2](docs/acceptance/KONTUR-EDIT-001-parametric-project-milestone.md).
Работа с другого устройства: [продолжение разработки](docs/CONTINUING-DEVELOPMENT.md).

## Возможности MVP

- загрузка PNG/JPEG через web;
- локальный анализ чертежа через авторизацию Codex CLI без OpenAI API key;
- цикл уточняющих вопросов по неуверенным размерам;
- строгие JSON Schema и типизированный CAD-IR перед обращением к движку;
- доверенный CAD-IR → build123d без исполнения сгенерированного кода;
- экспорт STEP/STL и независимая проверка повторно открытых файлов;
- «Мои модели», неизменяемая история CAD-IR, восстановление версии;
- размеры числом, ползунком и ограниченными текстовыми командами;
- новый открытый корпус и добавление сквозного отверстия в дне;
- независимая проверка STL: manifold, число тел, габариты и число сквозных
  отверстий;
- браузерное 3D-превью и скачивание артефактов;
- outbound-only worker, lease/idempotency, SHA-256 и DPAPI credential.

Движок проверяется на корпусах, втулках, кронштейнах и других моделях из
`tests/fixtures/cad-ir`. Это синтетический корпус проверок, не закрытая бета на
30 реальных деталях и не универсальное восстановление произвольной фотографии.

## Редактирование

В студии войдите и откройте раздел **Мои модели**. Можно создать корпус
120×80×40 мм со стенкой 3 мм либо сохранить готовую модель из своего заказа.
Размеры меняются без повторного анализа изображения. После каждой правки
создаётся новая версия и задание `BUILD_CAD`; следующий шаг доступен после
проверки геометрии. Политика модерации существующего развёртывания сохраняется.

Примеры команд: `ширина 140`, `длина 90`, `увеличь глубину на 10`,
`добавь отверстие диаметром 6 x 0 y 0`. Для других размеров указывайте имя
параметра из списка. Неполные или неоднозначные команды отклоняются.

История позволяет восстановить ранее проверенную версию. CAD-IR скачивается
кнопкой **Скачать редактируемый проект**; восстановление из загружаемого файла
пока не реализовано. Геометрические файлы — STEP и STL. Оплата ещё не подключена.

Новые таблицы создаёт миграция `0013_cad_projects`; стандартный `infra/migrate.sh`
подхватывает её по порядку. Новые endpoint'ы описаны в `schemas/openapi.v1.json`.

Проверяемый milestone: корпус → три последовательные правки → отверстие →
повторное открытие → корректные STL/STEP. Автоматический сквозной тест:

```powershell
python -m pytest -q apps/api/tests/test_projects.py packages/build123d-adapter/tests/test_project_editing.py
```

Нужны зависимости API, `apps/cad-worker/requirements.txt` и pytest; без build123d
реальные геометрические проверки пропускаются, что не означает их успешность.

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

На доверенном ПК нужны .NET 8 SDK, Codex CLI с локальной ChatGPT-авторизацией и
CAD worker build123d (Linux-контейнер в производстве, Python-процесс для разработки).

```powershell
dotnet run --project apps/local-worker/CadAi.LocalWorker.csproj -- probe-codex
dotnet run --project apps/local-worker/CadAi.LocalWorker.csproj -- describe-engine
dotnet run --project apps/local-worker/CadAi.LocalWorker.csproj -- enroll `
  --server http://localhost:8000 `
  --token <WORKER_ENROLLMENT_TOKEN>
dotnet run --project apps/local-worker/CadAi.LocalWorker.csproj -- run
```

Worker сам инициирует все соединения. На Windows credential сохраняется через
DPAPI в `%LOCALAPPDATA%\CadAiWorker`; Codex auth не передаётся API.

Подробные команды эксплуатации находятся в
[`docs/MVP-RUNBOOK.md`](docs/MVP-RUNBOOK.md), а доказательства приёмки — в
[`docs/TASK-011-014-mvp-drawing-web.md`](docs/TASK-011-014-mvp-drawing-web.md).

## Документация ранних этапов

В документах MVP ниже сохранена история ранней реализации. Актуальный движок
описан в [ADR-023](docs/adr/ADR-023-build123d-replaces-kompas.md).
В рабочем сервисе уже есть фундамент учёта себестоимости:

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

