# 12. Развёртывание и эксплуатация

## 1. VPS topology MVP

Один VPS:

```text
Caddy
 ├── web container
 └── api container
      ├── PostgreSQL
      ├── Redis
      ├── MinIO
      └── background worker
```

Production-ready вариант выносит PostgreSQL backup и object storage на отдельное устойчивое хранилище.

## 2. Docker Compose services

- `caddy`
- `web`
- `api`
- `backend-worker`
- `postgres`
- `redis`
- `minio`
- `minio-init`

## 3. Domains

```text
cad.example.com       web
api.cad.example.com   API при необходимости
files.cad.example.com object storage private endpoint
```

Предпочтительно same-origin web + `/api`, чтобы уменьшить CORS complexity.

## 4. Environment configuration

- `.env` не коммитится.
- production secrets — Docker secrets либо отдельный secret store.
- обязательная проверка конфигурации при startup.
- приложение не запускается с default secret.

## 5. Backup

- PostgreSQL: daily full + WAL/частые dumps по возможностям.
- Object storage: lifecycle + replica/backup.
- Encryption keys: отдельный backup.
- Restore drill минимум ежемесячно во время пилота.

## 6. Monitoring

### VPS metrics

- HTTP latency/errors;
- queue depth;
- active orders by state;
- storage usage;
- DB connections;
- failed background jobs;
- worker online status.

### Local metrics

- heartbeat age;
- current stage;
- free disk;
- Codex status;
- KOMPAS status;
- orphan process count;
- average build time;
- repair attempts.

## 7. Alerts

- worker offline > 5 min;
- queue waiting > threshold;
- disk < 15%;
- repeated auth failures;
- KOMPAS license unavailable;
- Codex auth required;
- five consecutive jobs failed;
- backup failed;
- TLS expiration.

## 8. Maintenance mode

Backend settings:

```json
{
  "accept_new_orders": false,
  "dispatch_ai_jobs": false,
  "dispatch_cad_jobs": false,
  "message": "Моделирование временно приостановлено"
}
```

## 9. Worker updates

- Worker сообщает текущую версию.
- Backend может установить `minimum_worker_version`.
- Update package подписан.
- Автоматическое обновление не выполняется во время job.
- Rollback на предыдущую версию.

## 10. Capacity MVP

- один CAD job одновременно;
- AI stages также последовательно, чтобы контролировать лимиты;
- frontend может принимать несколько заказов в очередь;
- показывать честный статус, без обещания точного времени;
- admin может ограничить число новых заказов.

## 11. Scaling

Первое масштабирование — добавить второй Windows worker с отдельной лицензией/разрешённым режимом. Backend уже маршрутизирует по capabilities и lease. Нельзя запускать несколько экземпляров КОМПАС только ради параллелизма без проверки лицензии.

## 12. Incident runbooks

Подготовить:

- Codex auth expired;
- Codex rate limited;
- KOMPAS hangs;
- license unavailable;
- VPS unavailable;
- storage unavailable;
- corrupt artifact;
- worker credential compromised;
- user data deletion request.
