# 16. Worker API и протокол событий

## 1. Claim request

```json
{
  "worker_id": "uuid",
  "capabilities": ["AI_DRAWING", "KOMPAS_BUILD"],
  "supported_cad_ir": ["0.1.0"],
  "available_slots": 1
}
```

## 2. Claim response

```json
{
  "job": {
    "job_id": "uuid",
    "order_id": "uuid",
    "job_type": "COMPILE_CAD_IR",
    "attempt": 1,
    "idempotency_key": "sha256:...",
    "lease_expires_at": "2026-07-27T15:00:00Z",
    "manifest_url": "short-lived-url",
    "required_output_schema": "cad-ir/0.1.0",
    "policy": {
      "model_route": "geometry_reasoning",
      "max_runtime_seconds": 900
    }
  }
}
```

Если задания нет:

```json
{"job": null, "retry_after_seconds": 5}
```

## 3. Heartbeat

```json
{
  "job_id": "uuid",
  "stage": "CAD_BUILDING",
  "progress": 0.45,
  "message_code": "FEATURE_BUILDING",
  "safe_details": {"feature_index": 5, "feature_count": 11}
}
```

`progress` является приблизительным и не используется для бизнес-логики.

## 4. Events

События append-only:

- `JOB_CLAIMED`
- `INPUT_DOWNLOADED`
- `AI_RUN_STARTED`
- `AI_RUN_COMPLETED`
- `QUESTIONS_READY`
- `CAD_IR_READY`
- `KOMPAS_STARTED`
- `FEATURE_COMPLETED`
- `VALIDATION_COMPLETED`
- `REPAIR_STARTED`
- `ARTIFACT_UPLOADED`
- `JOB_COMPLETED`
- `JOB_FAILED`

## 5. Complete

```json
{
  "job_id": "uuid",
  "idempotency_key": "sha256:...",
  "result": {
    "status": "success",
    "result_object_key": "...",
    "result_sha256": "...",
    "metrics": {
      "duration_ms": 120000,
      "codex_runs": 2,
      "cad_attempts": 1
    }
  },
  "artifacts": [
    {
      "type": "STL",
      "object_key": "...",
      "sha256": "...",
      "size_bytes": 12345
    }
  ]
}
```

## 6. Fail

```json
{
  "job_id": "uuid",
  "error": {
    "code": "CONTOUR_NOT_CLOSED",
    "safe_message": "Не удалось построить один из контуров детали.",
    "retryable": true,
    "requires_user_input": false,
    "diagnostic_fingerprint": "sha256:..."
  }
}
```

Сырые stack traces не отправлять пользователю. Backend может хранить ограниченную диагностическую сводку для admin.

## 7. Manifest

```json
{
  "manifest_version": "1.0",
  "job_id": "uuid",
  "order": {
    "units": "mm",
    "purpose": "3d_print",
    "requested_formats": ["stl", "step"]
  },
  "inputs": [
    {
      "id": "file-uuid",
      "kind": "normalized_drawing_page",
      "download_url": "...",
      "sha256": "...",
      "size_bytes": 1000000,
      "local_name": "page-001.png"
    }
  ],
  "context": [],
  "schemas": [],
  "expires_at": "..."
}
```

## 8. Compatibility

- Backend поддерживает N и N-1 worker protocol.
- Worker отклоняет unknown major version.
- Optional fields игнорируются.
- Enum unknown value приводит к safe rejection, а не default action.
