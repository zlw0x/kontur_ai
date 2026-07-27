# 05. ТЗ на локальный Windows-worker

## 1. Назначение

Local Worker является единственным компонентом, имеющим доступ одновременно к:

- Codex CLI, авторизованному пользовательским ChatGPT-аккаунтом;
- локальной установке КОМПАС-3D;
- временным файлам конкретного заказа;
- VPS worker API.

## 2. Формат приложения

На старте реализовать два режима:

1. `console` — для разработки и диагностики.
2. `tray` — для пилота, запускается после входа пользователя в Windows.

Windows Service добавлять только после проверки, что COM Automation КОМПАС стабильно работает в service/session-0 сценарии. Desktop CAD часто зависит от интерактивной пользовательской сессии, поэтому базовый production-вариант — tray app + автозапуск.

## 3. Команды CLI

```text
cad-worker enroll --server https://cad.example.com --token ...
cad-worker doctor
cad-worker run
cad-worker run-job ./path/to/job
cad-worker probe-kompas
cad-worker probe-codex
cad-worker logout
cad-worker diagnostics --output diagnostics.zip
```

## 4. Основные сервисы

```text
WorkerHost
 ├── ConfigurationService
 ├── EnrollmentService
 ├── ClaimLoop
 ├── LeaseManager
 ├── JobWorkspaceManager
 ├── InputDownloader
 ├── CodexRunner
 ├── AgentPipeline
 ├── KompasProcessManager
 ├── KompasAdapter
 ├── ValidationPipeline
 ├── ArtifactUploader
 ├── EventReporter
 └── CleanupService
```

## 5. Локальная конфигурация

Секреты не хранятся в TOML открытым текстом. В конфиге только ссылки на защищённые credentials.

```toml
server_url = "https://cad.example.com"
worker_name = "home-cad-01"
workspace_root = "D:/CadAiWorker/jobs"
max_parallel_jobs = 1
poll_timeout_seconds = 25
lease_heartbeat_seconds = 20
job_timeout_minutes = 30
retain_failed_jobs_days = 7
retain_success_jobs_hours = 12
kompas_executable = "C:/Program Files/ASCON/KOMPAS-3D/Bin/KOMPAS.Exe"
codex_executable = "C:/Users/USER/AppData/Roaming/npm/codex.cmd"
```

Worker credential хранить через Windows Credential Manager либо DPAPI.

## 6. Job workspace

```text
jobs/{job_id}/
  manifest.json
  input/
  context/
  schemas/
  prompts/
  agents/
  cad/
  output/
  logs/
  state.json
```

Правила:

- Путь создаётся самим worker.
- Имя пользовательского файла не используется как путь.
- Все скачанные файлы переименовываются в безопасные UUID.
- Worker проверяет sha256 после скачивания.
- В папку Codex копируется только необходимый контекст заказа.

## 7. Job execution

```text
claim
validate manifest
create workspace
download inputs
run stage
validate stage output
persist checkpoint
upload intermediate result if needed
complete or release
cleanup
```

Каждая стадия restartable. Состояние записывается атомарно через временный файл + rename.

## 8. Codex process isolation

Запускать Codex:

- с рабочей директорией задания;
- с `--ephemeral` для одноразовых стадий, где не нужен resume;
- с `--json` для журнала событий;
- с `--output-schema`;
- с `--sandbox workspace-write`;
- с `--ask-for-approval never` в полностью автоматической стадии;
- без `danger-full-access`;
- без сетевого доступа к произвольным доменам;
- с timeout;
- в Windows Job Object, чтобы убить дерево процессов при зависании.

## 9. Codex auth

- Владелец один раз выполняет `codex login` локально.
- Worker использует существующую локальную авторизацию Codex CLI.
- Worker не читает и не отправляет содержимое `~/.codex/auth.json`.
- `auth.json` исключён из diagnostics zip.
- При ошибке авторизации worker переходит в `AUTH_REQUIRED` и прекращает claim AI-заданий.

## 10. KOMPAS process management

Для каждого CAD job:

1. Проверить отсутствие зависшего экземпляра, принадлежащего worker.
2. Запустить отдельный instance или подключиться к созданному worker instance.
3. Записать PID.
4. Инициализировать COM в корректном apartment state.
5. Выполнить операции.
6. Сохранить документы.
7. Закрыть документы.
8. Запросить выход приложения.
9. Если процесс не завершился за timeout — завершить только PID worker instance.

Нельзя завершать все процессы `KOMPAS.exe`, поскольку пользователь может работать в своём экземпляре.

## 11. Capabilities

Worker при heartbeat отправляет:

```json
{
  "capabilities": {
    "codex": true,
    "kompas_3d": true,
    "operations": ["extrude_add", "hole", "chamfer"],
    "formats": ["m3d", "step", "stl"],
    "max_parallel_jobs": 1
  },
  "versions": {
    "worker": "0.1.0",
    "codex_cli": "0.144.0",
    "kompas": "24.x",
    "cad_ir_schema": "0.1.0"
  }
}
```

## 12. Local health states

- `STARTING`
- `READY`
- `BUSY`
- `PAUSED`
- `AUTH_REQUIRED`
- `KOMPAS_UNAVAILABLE`
- `UPDATE_REQUIRED`
- `DEGRADED`
- `STOPPING`

## 13. Doctor checks

`cad-worker doctor` проверяет:

- DNS и TLS VPS;
- worker credential;
- свободное место;
- доступность Codex CLI;
- текущую авторизацию Codex;
- доступность выбранных моделей;
- наличие КОМПАС;
- версию SDK/type libraries;
- создание временного 3D-документа;
- экспорт тестового STL;
- права записи workspace;
- отсутствие секретов в логах.

## 14. Acceptance criteria

- Worker переживает перезапуск во время скачивания.
- Worker переживает перезапуск между CAD build и upload.
- Зависший Codex завершается по timeout.
- Зависший worker-instance КОМПАС завершается без воздействия на пользовательский instance.
- Ни один секрет не попадает в логи.
- Offline VPS приводит к exponential backoff, а не tight loop.
