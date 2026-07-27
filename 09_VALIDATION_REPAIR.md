# 09. Валидация и автоматическое исправление

## 1. Уровни проверки

### Уровень A. Входной документ

- файл читается;
- разрешение достаточно;
- чертёж не обрезан;
- размерные надписи видимы;
- определены единицы либо требуется вопрос;
- нет признаков нескольких несвязанных деталей без явного выбора.

### Уровень B. Drawing analysis

- все распознанные размеры имеют source bbox;
- confidence находится в диапазоне 0..1;
- противоречащие размеры не скрываются;
- неуверенное значение не помечается confirmed;
- виды связаны между собой.

### Уровень C. CAD-IR static validation

- JSON Schema;
- feature dependency graph;
- expressions;
- references;
- допустимые диапазоны;
- unresolved usage;
- operation count;
- обязательные invariants.

### Уровень D. KOMPAS build validation

- каждая feature построена;
- document rebuild успешен;
- одно твёрдое тело;
- нет подавленных из-за ошибки операций;
- сохранение и экспорт успешны.

### Уровень E. Геометрия

- bounding box;
- объём;
- площадь;
- отверстия;
- оси и расстояния;
- симметрия;
- минимальная толщина;
- сравнение с expected invariants.

### Уровень F. Mesh

- STL читается;
- mesh watertight;
- нормали согласованы;
- нет degenerate triangles;
- нет self-intersections в доступной степени проверки;
- размер и масштаб совпадают;
- число компонентов ожидаемо.

### Уровень G. Визуальный аудит

- ортогональные рендеры построенной модели;
- сравнение внешних контуров с чертежом;
- проверка грубых пропусков;
- визуальный аудит никогда не отменяет числовую ошибку.

## 2. Validation report

```json
{
  "status": "failed",
  "attempt": 1,
  "checks": [
    {
      "id": "bbox",
      "status": "failed",
      "expected": [60, 40, 23],
      "actual": [60, 40, 15],
      "tolerance": 0.05,
      "severity": "error",
      "related_features": ["f_boss"]
    }
  ],
  "repairable": true,
  "repair_context": {
    "suspected_feature": "f_boss",
    "error_class": "missing_or_wrong_extrusion"
  }
}
```

## 3. Repair loop

```text
build attempt
  -> deterministic validator
  -> classify error
  -> if deterministic fix exists: apply without LLM
  -> else invoke repair agent
  -> validate JSON Patch
  -> create new CAD-IR version
  -> rebuild from empty document
```

## 4. Детерминированные исправления

Без Codex исправлять:

- незамкнутый контур из-за зазора меньше установленного epsilon;
- отрицательное направление выдавливания при однозначном bbox mismatch;
- неверное расширение STL;
- отсутствие output directory;
- transient COM retry;
- export retry после rebuild;
- округление floating point в пределах schema tolerance.

Нельзя детерминированно «угадывать» неизвестную глубину отверстия.

## 5. Repair agent contract

Вход:

- immutable confirmed facts;
- текущий CAD-IR;
- build errors;
- validation report;
- feature catalog;
- список разрешённых patch paths.

Выход:

```json
{
  "decision": "patch",
  "reason": "Feature f_boss uses 7 mm instead of confirmed 15 mm.",
  "patch": [
    {
      "op": "replace",
      "path": "/features/1/inputs/distance",
      "value": {"param": "p_boss_height"}
    }
  ],
  "affected_features": ["f_boss"],
  "confidence": 0.96
}
```

Repair agent запрещено менять:

- user-confirmed parameters;
- source file;
- schema version;
- security settings;
- expected invariant, если именно он выявил ошибку;
- историю provenance.

## 6. Stop conditions

Repair прекращается, если:

- три попытки исчерпаны;
- одинаковый error fingerprint повторился дважды;
- patch не изменяет CAD-IR hash;
- требуется новый пользовательский факт;
- confidence repair ниже threshold;
- изменяется confirmed параметр;
- обнаружена неподдерживаемая геометрия.

Результат переводится в `WAITING_FOR_USER_ANSWERS` либо `MANUAL_REVIEW`.

## 7. Golden comparison

Для тестовых fixtures хранить:

- input drawing;
- expected extraction;
- expected CAD-IR;
- expected STEP/STL hash не использовать как единственный критерий;
- expected geometry fingerprint;
- expected renders;
- known acceptable variation.

Geometry fingerprint:

```json
{
  "bbox": [60, 40, 23],
  "volume": 48600.25,
  "surface_area": 12120.2,
  "solid_count": 1,
  "cylindrical_faces": [10, 30],
  "mesh_components": 1
}
```

## 8. Manual review package

При ручной проверке оператор получает:

- исходный файл;
- вопросы и ответы;
- CAD-IR versions diff;
- все build errors;
- последний M3D, если создан;
- STEP/STL;
- рендеры;
- validation report;
- краткое AI summary без скрытого reasoning.
