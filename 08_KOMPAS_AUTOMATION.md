# 08. Автоматизация КОМПАС-3D

## 1. Главный принцип

Codex не пишет одноразовый произвольный скрипт КОМПАС для каждого заказа. Codex создаёт CAD-IR. Проверенный `KompasAdapter` переводит CAD-IR в вызовы API.

## 2. Adapter layers

```text
CAD-IR
  ↓
CadIrValidator
  ↓
FeaturePlanner
  ↓
IKompasCadSession
  ↓
KompasApiV7Adapter / KompasApi5Fallback
  ↓
КОМПАС-3D
```

Конкретную API-ветку выбрать после probe установленной версии. Не смешивать вызовы разных API без отдельного compatibility layer.

## 3. Interfaces

```csharp
public interface ICadSession : IAsyncDisposable
{
    Task<PartHandle> CreatePartAsync(PartOptions options, CancellationToken ct);
    Task<BuildResult> ExecuteFeatureAsync(PartHandle part, CadFeature feature, CancellationToken ct);
    Task<ValidationSnapshot> InspectAsync(PartHandle part, CancellationToken ct);
    Task SaveAsync(PartHandle part, string path, CancellationToken ct);
    Task ExportStepAsync(PartHandle part, string path, CancellationToken ct);
    Task ExportStlAsync(PartHandle part, string path, StlExportOptions options, CancellationToken ct);
    Task<string> RenderPreviewAsync(PartHandle part, PreviewOptions options, CancellationToken ct);
}
```

## 4. Feature handlers

Каждый feature type имеет отдельный handler:

```text
IFeatureHandler
  CanHandle(type)
  Validate(feature, context)
  Execute(session, feature, references)
  InspectResult(...)
```

Нельзя делать один giant switch с сотнями строк.

## 5. COM discipline

- COM инициализируется на выделенном STA thread.
- Все COM-вызовы выполняются на этом же thread.
- COM references освобождаются детерминированно.
- RCW не сохраняются в static state.
- Ошибки HRESULT переводятся в собственные error codes.
- Каждая операция имеет timeout на уровне orchestration.
- После операции выполняется rebuild/update и проверка результата.

## 6. Stable references

После создания feature adapter записывает semantic map:

```json
{
  "feature.f_base": {
    "result_body": "internal-handle",
    "end_face_selector": {
      "normal": [0, 0, 1],
      "extreme": "max"
    }
  }
}
```

В persisted state нельзя сохранять сырые COM pointers. После перезапуска semantic map восстанавливается путём инспекции дерева модели и атрибутов, назначенных объектам.

## 7. Custom attributes

Если API позволяет, каждому созданному feature/эскизу назначать пользовательский атрибут `cad_ai_feature_id`. Это упрощает повторную идентификацию после rebuild.

## 8. Export

### STL

- binary STL;
- единицы миллиметры;
- настраиваемая точность аппроксимации;
- разумный предел количества треугольников;
- после экспорта обязательна mesh validation.

### STEP

- сохранять как точную B-Rep обменную модель;
- после экспорта выполнять повторное чтение внешней библиотекой, если доступно;
- сверять bounding box.

### M3D

- основная модель для аудита и ручной доработки;
- имя файла не содержит пользовательский ввод;
- сохранять после успешного rebuild.

## 9. Transaction-like build

КОМПАС не является транзакционной БД. Поэтому каждая попытка строится в новом документе:

```text
attempt-01/model.m3d
attempt-02/model.m3d
attempt-03/model.m3d
```

Не исправлять production result in-place. После успешной проверки выбранная попытка копируется в `output/`.

## 10. Error taxonomy

- `KOMPAS_NOT_INSTALLED`
- `KOMPAS_LICENSE_UNAVAILABLE`
- `KOMPAS_START_TIMEOUT`
- `COM_INITIALIZATION_FAILED`
- `DOCUMENT_CREATE_FAILED`
- `SKETCH_INVALID`
- `CONTOUR_NOT_CLOSED`
- `FEATURE_BUILD_FAILED`
- `REFERENCE_NOT_FOUND`
- `REFERENCE_AMBIGUOUS`
- `REBUILD_FAILED`
- `SAVE_FAILED`
- `STEP_EXPORT_FAILED`
- `STL_EXPORT_FAILED`
- `KOMPAS_PROCESS_HUNG`
- `UNSUPPORTED_KOMPAS_VERSION`

Каждая ошибка содержит `feature_id`, stage, safe message и local diagnostic details.

## 11. Probe suite

До реализации всех features создать автоматические probes:

1. Application connect/start.
2. New 3D part.
3. Sketch rectangle.
4. Extrude.
5. Hole.
6. Fillet.
7. Chamfer.
8. Circular pattern.
9. Save M3D.
10. Export STEP.
11. Export STL.
12. Reopen and inspect.

## 12. Acceptance criteria

- Один CAD-IR строится одинаково после десяти повторов.
- При неверном contour возвращается конкретный error code.
- При отсутствии лицензии worker не зависает.
- Пользовательский открытый КОМПАС не закрывается.
- Semantic references устойчивы к изменению не связанного размера.
