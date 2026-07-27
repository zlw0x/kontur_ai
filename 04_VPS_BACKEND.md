# 04. ТЗ на VPS backend и web

## 1. Backend modules

```text
app/
  auth/
  users/
  orders/
  uploads/
  questions/
  plans/
  jobs/
  workers/
  artifacts/
  billing/
  audit/
  notifications/
  admin/
```

Модули не должны напрямую менять таблицы соседнего bounded context. Для переходов заказа использовать `OrderStateService`.

## 2. Основные сущности базы

### users

- id UUID
- email
- password_hash
- role
- status
- created_at
- last_login_at

### orders

- id UUID
- user_id
- status
- version
- title
- source_units
- requested_formats
- purpose
- user_comment
- active_plan_version
- active_cad_ir_version
- created_at
- updated_at
- expires_at

### order_files

- id
- order_id
- kind
- object_key
- original_name
- mime_type
- sha256
- size_bytes
- page_count
- created_at

### clarification_questions

- id
- order_id
- analysis_version
- feature_ref
- question_type
- question_text
- options_json
- crop_object_key
- confidence
- status
- created_at

### clarification_answers

- id
- question_id
- user_id
- answer_json
- created_at

### cad_ir_versions

- id
- order_id
- version
- source
- schema_version
- object_key
- sha256
- parent_version
- change_summary
- created_at

### jobs

- id
- order_id
- job_type
- status
- priority
- payload_object_key
- idempotency_key
- required_capabilities
- attempt
- max_attempts
- lease_owner
- lease_expires_at
- available_at
- created_at
- started_at
- finished_at
- error_code
- error_summary

### local_workers

- id
- name
- token_hash
- status
- capabilities_json
- app_version
- kompas_version
- codex_version
- last_seen_at
- current_job_id

### artifacts

- id
- order_id
- job_id
- artifact_type
- object_key
- sha256
- size_bytes
- metadata_json
- created_at

### audit_events

- id
- actor_type
- actor_id
- order_id
- action
- metadata_json
- created_at

## 3. API conventions

- Prefix `/api/v1`.
- JSON only, кроме upload/download.
- RFC 7807 Problem Details для ошибок.
- `X-Request-ID` на каждом запросе.
- Optimistic locking через `version` заказа.
- Idempotency header для mutation endpoints.
- Все timestamps в UTC.
- UUIDv7 либо UUIDv4.

## 4. Пользовательские endpoints

```text
POST   /auth/register
POST   /auth/login
POST   /auth/refresh
POST   /auth/logout
GET    /orders
POST   /orders
GET    /orders/{id}
POST   /orders/{id}/files
POST   /orders/{id}/submit
GET    /orders/{id}/questions
POST   /orders/{id}/answers
GET    /orders/{id}/plan
POST   /orders/{id}/plan/approve
POST   /orders/{id}/plan/reject
GET    /orders/{id}/artifacts
POST   /orders/{id}/revisions
```

## 5. Worker endpoints

```text
POST /workers/register
POST /workers/heartbeat
POST /workers/claim
POST /workers/jobs/{job_id}/heartbeat
POST /workers/jobs/{job_id}/events
POST /workers/jobs/{job_id}/complete
POST /workers/jobs/{job_id}/fail
POST /workers/jobs/{job_id}/release
POST /workers/uploads/presign
GET  /workers/jobs/{job_id}/input-manifest
```

## 6. Worker authentication

- При первичной регистрации admin создаёт одноразовый enrollment token.
- Worker генерирует локальный key pair.
- Backend выдаёт постоянный worker credential.
- В MVP допустим длинный случайный bearer token, хранимый через Windows DPAPI.
- Backend хранит только hash токена.
- Credential можно отозвать.
- Ограничить worker endpoints по rate limit и отдельной auth-схеме.

## 7. File pipeline

1. Frontend запрашивает presigned upload URL.
2. Загружает файл напрямую в S3.
3. Backend получает finalize с sha256.
4. Background worker проверяет magic bytes, MIME и размер.
5. PDF переводится в PNG страниц в sandboxed container.
6. Создаётся normalized input manifest.
7. Локальному worker выдаются краткоживущие download URLs.

## 8. Frontend pages

```text
/
/login
/register
/dashboard
/orders/new
/orders/{id}
/orders/{id}/questions
/orders/{id}/plan
/orders/{id}/result
/admin/orders
/admin/workers
/admin/settings
```

## 9. UI заказа

Timeline:

- файл принят;
- проверка качества;
- анализ;
- ожидается ответ;
- план готов;
- моделирование;
- проверка;
- результат.

Пользователь не должен видеть внутренние слова `Codex`, `COM`, `worker lease` или сырые исключения.

## 10. 3D preview

- Использовать Three.js или `<model-viewer>`.
- На сервере конвертировать STEP/M3D в glTF/GLB только отдельным безопасным converter-процессом.
- Для MVP можно визуализировать STL напрямую.
- Показывать оси, сетку, габариты и единицы.

## 11. Admin UI

- очередь заказов;
- online/offline worker;
- текущая стадия;
- логи без секретов;
- повтор задания;
- перевод в manual review;
- просмотр вопросов, ответов, CAD-IR и отчёта;
- остановка приёма новых заказов;
- emergency revoke worker.

## 12. Backend acceptance criteria

- Полный integration test машины состояний.
- Невозможен недопустимый переход.
- Дублирующий completion не создаёт повторные artifacts.
- Просроченный lease переходит в retry.
- Worker не может получить заказ без нужной capability.
- Пользователь не может получить чужой файл по ID.
