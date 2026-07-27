# 07. Спецификация CAD-IR

## 1. Назначение

CAD-IR — версионированное, строго валидируемое, независимое от КОМПАС описание детали. Оно является единственным допустимым входом CAD builder.

## 2. Принципы

- Внутренняя единица — миллиметр.
- Каждая сущность имеет стабильный `id`.
- Операции ссылаются на semantic references, а не на нестабильные индексы граней КОМПАС.
- Каждый числовой параметр содержит provenance.
- Неуверенные параметры явно помечены.
- Никаких исполняемых выражений общего назначения.
- Только ограниченный expression language для параметров.

## 3. Верхний уровень

```json
{
  "schema_version": "0.1.0",
  "part": {},
  "parameters": [],
  "reference_geometry": {},
  "features": [],
  "expected_invariants": [],
  "assumptions": [],
  "unresolved": [],
  "provenance": {}
}
```

## 4. Parameters

```json
{
  "id": "p_base_width",
  "name": "Base width",
  "value": 60.0,
  "unit": "mm",
  "tolerance": null,
  "status": "confirmed",
  "source": {
    "type": "drawing_dimension",
    "page": 1,
    "bbox": [0.12, 0.30, 0.22, 0.34],
    "raw_text": "60"
  },
  "confidence": 0.99
}
```

`status`:

- `confirmed`
- `user_confirmed`
- `inferred`
- `assumed`
- `unresolved`

Значение со статусом `unresolved` запрещено использовать в buildable feature.

## 5. Feature base

```json
{
  "id": "f_base",
  "type": "extrude_add",
  "enabled": true,
  "depends_on": [],
  "inputs": {},
  "semantic_outputs": ["body.main", "face.base.top"],
  "source_refs": []
}
```

## 6. Sketch representation

Эскиз задаётся геометрией и ограничениями:

```json
{
  "id": "sk_base",
  "plane": "XY",
  "entities": [
    {
      "id": "rect_1",
      "type": "center_rectangle",
      "center": [0, 0],
      "width": {"param": "p_base_width"},
      "height": {"param": "p_base_height"}
    }
  ],
  "constraints": [
    {"type": "horizontal", "entity": "rect_1.edge.top"},
    {"type": "vertical", "entity": "rect_1.edge.left"}
  ],
  "expected_closed_contours": 1
}
```

## 7. Semantic references

Нельзя хранить `face_index=7`. После перестроения индекс изменится.

Допустимые ссылки:

- `body.main`
- `feature.f_base.result_body`
- `face.f_base.end`
- `face.f_base.start`
- `axis.global.z`
- `edge.f_base.outer_top[all]`
- `face.by_normal(+Z).max_z`

Adapter разрешает semantic reference через набор контролируемых selector strategies и проверяет, что найден ровно ожидаемый набор.

## 8. Supported features v0.1

### extrude_add / extrude_cut

- sketch
- direction
- distance или through_all
- symmetric
- draft_angle

### revolve_add / revolve_cut

- profile
- axis
- angle

### hole

- placement plane/face
- center
- diameter
- depth/through_all
- countersink/counterbore limited
- thread metadata

### fillet

- edge selector
- radius

### chamfer

- edge selector
- distance + angle либо two distances

### patterns

- linear: direction, count, spacing
- circular: axis, count, total_angle

### mirror

- source features
- plane

## 9. Invariants

```json
{
  "id": "inv_bbox",
  "type": "bounding_box",
  "expected": [60, 40, 23],
  "tolerance": 0.05,
  "severity": "error"
}
```

Другие типы:

- `solid_body_count`
- `volume_range`
- `surface_area_range`
- `hole_count`
- `cylindrical_face_diameter`
- `distance_between_axes`
- `symmetry`
- `minimum_wall_thickness`
- `mesh_watertight`
- `feature_build_status`

## 10. Expression language

Допускаются:

- числа;
- ссылки на параметры;
- `+ - * /`;
- скобки;
- функции `min`, `max`, `abs`;
- константа `pi`.

Запрещены вызовы системных функций, строки как код, файловые пути и reflection.

Пример:

```json
{"expr": "p_outer_diameter / 2 - p_wall"}
```

## 11. Traceability

Каждый feature должен быть связан с:

- размером чертежа;
- ответом пользователя;
- явным инженерным допущением;
- либо геометрическим следствием других подтверждённых параметров.

Финальный отчёт должен позволять ответить: «Откуда взялся размер 8 мм?»

## 12. Versioning

- Patch: уточнение schema без изменения смысла.
- Minor: новые optional feature types.
- Major: несовместимая структура.

Worker публикует поддерживаемый диапазон версии. Backend не выдаёт ему несовместимый CAD-IR.

## 13. Build eligibility

CAD-IR допускается к построению, только если:

- schema valid;
- нет unresolved параметров, используемых features;
- feature graph acyclic;
- все references существуют;
- выражения вычисляются;
- размеры конечны и в диапазонах;
- operation count не превышен;
- нет запрещённых feature types;
- invariants присутствуют минимум для bounding box и body count.
