# CAD AI Service — Post-MVP Roadmap

**Назначение:** продолжение подтверждённого вертикального MVP  
**Рекомендуемый путь:** `docs/POST-MVP-ROADMAP.md`  
**Версия:** 1.0  
**Дата:** 2026-07-27

## 1. Исходная точка

Подтверждённый MVP уже умеет:

- загружать PNG/JPEG;
- выполнять локальный анализ через Codex CLI;
- задавать уточняющие вопросы;
- формировать и строго валидировать CAD-IR;
- строить в КОМПАС-3D прямоугольную призму и до 19 круглых сквозных отверстий;
- выполнять ограниченный repair loop;
- экспортировать M3D, STEP и STL;
- независимо проверять bounding box, число отверстий и manifold STL;
- показывать STL в браузере;
- восстанавливать задания после перезапуска.

Цель следующего этапа — расширить сервис до широкого класса параметрических механических деталей, корпусов, кронштейнов и токарных деталей, не разрушая детерминированность и безопасность MVP.

## 2. Основной принцип расширения

Нельзя пытаться добавить «весь КОМПАС-3D» одним большим агентным заданием. Каждая новая функция проходит один и тот же конвейер:

1. CAD-IR Schema;
2. semantic validator;
3. fake adapter;
4. реальный KompasAdapter;
5. independent geometry verifier;
6. positive/negative fixtures;
7. resource instrumentation;
8. feature flag;
9. capability manifest;
10. reliability gate.

Сохраняется обязательная граница:

```text
Чертёж
  -> Codex CLI
  -> versioned CAD-IR JSON
  -> JSON Schema
  -> semantic validator
  -> whitelist CAD operations
  -> KompasAdapter
  -> КОМПАС-3D
```

LLM не должен генерировать и запускать произвольный Python, PowerShell или C#.

## 3. Что сделать до новых CAD-операций

### POSTMVP-001 — Resource Ledger

Добавить append-only журнал ресурсов задания:

- AI runs;
- process/script runs;
- CAD sessions;
- CAD attempts;
- individual feature operations;
- rebuilds;
- repair iterations;
- exports;
- validation;
- preview rendering;
- upload/download;
- human review.

### POSTMVP-002 — Cost Engine

Добавить:

- versioned pricing profiles;
- subscription allocation для ChatGPT/Codex;
- API-equivalent shadow price;
- стоимость локального worker;
- стоимость VPS/storage;
- budget guard;
- final immutable cost snapshot.

### POSTMVP-003 — Capability Registry

Worker публикует manifest:

```json
{
  "worker_version": "0.4.0",
  "kompas_version": "24.x",
  "cad_ir_versions": ["1.0", "1.1"],
  "capabilities": {
    "solid.rectangular_prism": "stable",
    "feature.hole.simple_through": "stable",
    "solid.revolve": "unsupported"
  }
}
```

Статусы: `unsupported`, `experimental`, `beta`, `stable`, `disabled`.

VPS не выдаёт worker задание, если manifest не покрывает необходимые операции.

### POSTMVP-004 — CAD-IR versioning

Добавить:

- `cad_ir_version`;
- schema migrations;
- canonical JSON serialization;
- stable feature IDs;
- reject future unsupported schemas;
- backward compatibility минимум на одну предыдущую версию.

### POSTMVP-005 — Semantic geometry selectors

Запретить выбор граней и рёбер только по нестабильному индексу. Использовать семантические selectors:

```json
{
  "kind": "planar_face",
  "normal": [0, 0, 1],
  "extreme": "max_z",
  "area_near_mm2": 800,
  "tolerance_mm": 0.1
}
```

При нескольких совпадениях — typed ambiguity error, а не случайный выбор.

---

# Этап P1 — эскизы и datum-геометрия

## P1.1. Примитивы эскиза

- point;
- line/construction line;
- rectangle: corner, center, rotated;
- circle;
- arc;
- ellipse;
- polygon;
- slot;
- polyline;
- spline;
- rounded rectangle;
- trim/extend;
- offset/equidistant;
- mirror/copy entities.

## P1.2. Ограничения

- horizontal/vertical;
- parallel/perpendicular;
- tangent;
- concentric;
- coincident;
- midpoint;
- equal;
- symmetry;
- fixed;
- collinear.

## P1.3. Размеры

- linear/aligned;
- horizontal/vertical;
- radial/diameter;
- angular;
- coordinate;
- distance between entities.

Каждый управляющий размер получает стабильное имя: `base_width`, `hole_pitch_x`, `wall_thickness`.

## P1.4. Проверка эскиза

До формообразующей операции проверять:

- closed contours;
- self-intersections;
- zero-length entities;
- duplicates;
- micro-gaps;
- contour nesting;
- expected area;
- conflicting constraints;
- степень определённости.

Автолечение разрешать только для микрозазоров меньше configurable tolerance и фиксировать в assumptions.

## P1.5. Datum geometry

- standard planes;
- offset plane;
- angled plane;
- plane through three points;
- plane through edge and point;
- tangent plane;
- axis by two points;
- axis from cylindrical face;
- datum point;
- local coordinate system.

**Gate P1:** минимум 50 fixtures, каждый прогоняется на 20 наборах параметров.

---

# Этап P2 — базовые твердотельные операции

## P2.1. Extrude/Cut

Расширить текущую операцию:

- new body/join/cut/intersect;
- one side/two sides/symmetric;
- through all;
- up to face/body;
- draft angle;
- thin feature;
- multiple sketch regions.

## P2.2. Revolve

- full/partial angle;
- one/two directions;
- new body/join/cut;
- thin revolve;
- explicit axis reference;
- automatic axis inference только при высокой уверенности.

Целевые детали: втулки, шайбы, шкивы, штуцеры, крышки, токарные профили.

## P2.3. Hole families

- simple through/blind;
- counterbore;
- countersink;
- stepped;
- threaded designation;
- depth to face;
- hole by coordinates/on face;
- hole pattern.

Настоящую геометрию резьбы вынести в отдельную advanced capability.

## P2.4. Chamfer/Fillet

- equal-distance chamfer;
- two-distance chamfer;
- distance-angle chamfer;
- constant-radius fillet;
- multiple selected edges;
- tangent chain только при однозначном выборе.

## P2.5. Patterns

- linear;
- circular;
- grid;
- mirror feature/body;
- pattern along curve;
- skipped instances.

## P2.6. Boolean и multi-body

- union;
- subtraction;
- intersection;
- keep/delete tool bodies;
- body naming;
- active body;
- expected body count.

**Gate P2:** 100 golden-моделей, 30 типов деталей, 99% deterministic build success на synthetic corpus.

---

# Этап P3 — инженерные features

## P3.1. Shell

- inward/outward/both;
- remove selected faces;
- constant wall thickness;
- minimum wall validation.

## P3.2. Rib

- rib from sketch;
- one side/symmetric;
- thickness;
- draft;
- extent to next face.

## P3.3. Draft

- neutral plane;
- pull direction;
- selected faces;
- positive/negative angle;
- self-intersection check.

## P3.4. Threads

Разделить режимы:

1. `thread.designation` — условная резьба;
2. `thread.modeled` — реальная винтовая геометрия для STL.

Параметры modeled thread:

- standard/custom profile;
- pitch;
- handedness;
- internal/external;
- length;
- lead-in;
- printable clearance.

## P3.5. Высокоуровневые типовые features

- rectangular/circular pocket;
- keyway;
- groove;
- O-ring groove;
- slot cut;
- mounting boss;
- standoff;
- vent pattern;
- cable gland hole.

Они компилируются в низкоуровневые операции, но упрощают reasoning модели.

## P3.6. Physical properties

- material;
- density;
- mass;
- volume;
- surface area;
- center of mass.

**Gate P3:** корпуса, крышки и печатные детали строятся без ручного вмешательства; modeled threads проходят manifold check.

---

# Этап P4 — сложные профили и 3D-кривые

## P4.1. Sweep / кинематическая операция

- 2D/3D path;
- join/cut/new body;
- orientation modes;
- guide curve;
- controlled twist;
- pipe/duct templates.

## P4.2. Loft / операция по сечениям

- two or more profiles;
- guide curves;
- vertex correspondence;
- open/closed profiles;
- join/cut/new body;
- topology validation.

## P4.3. 3D curves

- 3D polyline;
- 3D spline;
- cylindrical/conical helix;
- intersection/projected curve;
- imported points.

## P4.4. Templates

- compression spring;
- auger;
- helical groove;
- real external/internal thread.

**Gate P4:** loft/sweep имеют topology oracle; неоднозначное сопоставление сечений отклоняется.

---

# Этап P5 — поверхностное моделирование

- extrusion/revolution/sweep/loft surface;
- ruled/plane surface;
- NURBS where API is stable;
- trim/extend/offset;
- intersection curve;
- patch;
- sew;
- thicken;
- remove/replace face;
- closed-shell to solid.

Ограничения:

- organic reconstruction from one photo не гарантируется;
- Class-A surfaces вне scope;
- freeform models идут в manual-review tariff;
- agent обязан формировать явные sections/guides.

---

# Этап P6 — листовой металл

Отдельный domain CAD-IR:

- base flange;
- edge flange;
- bend;
- hem;
- jog;
- cutout;
- corner relief;
- unfold/refold;
- flat pattern;
- DXF export.

Обязательные параметры: thickness, bend radius, K-factor/bend allowance, relief type.

Проверки: uniform thickness, collisions, valid flat pattern, minimum bend radius warning.

---

# Этап P7 — детали и сборки

- create/insert components;
- fixed component;
- coincident/concentric/distance/angle mates;
- component patterns;
- interference check;
- exploded preview;
- per-part STL/STEP;
- assembly STEP;
- ZIP package.

При неоднозначном сопряжении — вопрос пользователю или manual review.

---

# Этап P8 — расширение анализа чертежей

Расширять vision pipeline только после поддержки соответствующей геометрии в adapter.

## Форматы

- PNG/JPEG/WEBP через isolated image sanitizer;
- multi-page PDF через отдельный isolated rasterizer;
- канонические PNG pages, overview и tiles для крупных листов;
- scans;
- perspective-corrected photos.

Утверждённая политика входа, лимиты и security acceptance описаны в
[SECURE-INPUT-ADDENDUM.md](SECURE-INPUT-ADDENDUM.md). DXF, DWG, TIFF и прочие
форматы не входят в текущий утверждённый scope.

## Обозначения

- diameters/radii;
- chamfers;
- threads/depth;
- fits/tolerances;
- roughness;
- базовые GD&T;
- sections/local sections;
- detail views;
- tables of holes;
- technical requirements.

## Evidence graph

```text
dimension -> drawing entity -> view -> inferred 3D feature -> CAD operation
```

Каждый вывод хранит evidence, confidence, source bounding box, assumption и clarification requirement.

## Web editor

До построения пользователь может:

- исправить размер;
- привязать размер к другому элементу;
- выбрать through/blind;
- выбрать грань;
- изменить резьбу;
- отключить сомнительную операцию.

---

# Этап P9 — production hardening

## Worker reliability

- concurrency=1 по умолчанию;
- Windows Job Object;
- process watchdog;
- session recycling;
- forced cleanup;
- disk quota;
- resumable upload;
- orphan cleanup;
- reboot policy после серии сбоев.

## Quality score

```json
{
  "quality_score": 0.96,
  "drawing_confidence": 0.91,
  "cad_build_confidence": 1.0,
  "geometry_validation": 0.99,
  "assumption_count": 1,
  "repair_count": 1,
  "manual_review_required": false
}
```

## Budget limits

```json
{
  "max_ai_runs": 8,
  "max_total_tokens": 300000,
  "max_cad_attempts": 4,
  "max_repairs": 2,
  "max_worker_seconds": 1800,
  "max_internal_cost_rub": 500
}
```

При превышении: остановка, запрос доплаты или manual review.

---

## 4. Распределение моделей Codex

| Роль | Default | Effort | Escalation |
|---|---|---:|---|
| normalization/structured extraction | GPT-5.6 Luna | low/medium | Terra |
| drawing geometry reasoning | GPT-5.6 Terra | medium | Sol high |
| clarification questions | Terra | medium | Sol при сложной неоднозначности |
| CAD plan | Terra | medium | Sol для loft/surface |
| CAD-IR serialization | Luna | low | Terra при schema failure |
| schema/semantic checks | Luna | low | Terra repair |
| repair classification | Terra | medium | Sol после неудачи Terra |
| simple final audit | Luna | medium | Terra |
| advanced final audit | Terra | high | Sol high |

Правила:

- не использовать Ultra в пользовательских автоматических заказах;
- Fast mode выключен по умолчанию;
- Sol запускается только по escalation policy;
- минимальный context для каждого агента;
- исходное изображение не отправлять повторно, если достаточно structured facts;
- отдельный небольшой AGENTS.md для каждой роли.

## 5. Golden corpus

```text
samples/golden/
  simple-prismatic/
  turned/
  enclosures/
  patterns/
  shell-rib/
  sweep-loft/
  surfaces/
  sheet-metal/
  negative/
```

Для каждого fixture:

- source drawing;
- canonical CAD-IR;
- expected operation tree;
- expected dimensions/topology;
- normalized result signature;
- screenshots;
- tolerances;
- maximum attempts;
- resource baseline.

## 6. Definition of Done для новой операции

Операция становится `stable`, если:

- есть schema и semantic validator;
- fake и real adapter;
- independent verifier;
- минимум 10 positive и 10 negative fixtures;
- parameterized tests;
- typed errors;
- resource ledger integration;
- feature flag и rollback;
- 100 последовательных E2E без process leak.

## 7. Рекомендуемые релизы

### 0.4 — Instrumented MVP

Ledger, cost snapshots, capability registry, CAD-IR versioning.

### 0.5 — Parametric Parts

Sketches, constraints, extrude/revolve, holes, fillet/chamfer, patterns, booleans.

### 0.6 — Engineering Parts

Shell, ribs, draft, grooves, modeled threads, multi-body, physical properties.

### 0.7 — Advanced Geometry

Sweep, loft, 3D curves, springs.

### 0.8 — Surfaces and Sheet Metal

Отдельные tariffs и quality gates.

### 0.9 — Assemblies

Multi-part orders, mates, interference.

### 1.0 — Public Production

Calibrated pricing, payments, quotas, support workflow, manual review, monitoring.

## 8. Первые задачи

1. POSTMVP-001 Resource Ledger — сделано
2. POSTMVP-002 Cost Engine — сделано
3. POSTMVP-003 Capability Registry — сделано
4. POSTMVP-004 CAD-IR v1.1 — сделано
5. POSTMVP-005 Semantic Selectors — сделано
6. POSTMVP-006 Sketch Primitives — сделано
7. POSTMVP-007 Sketch Constraints — сделано
8. POSTMVP-008 Revolve — **не начат на КОМПАС, перенесён на build123d** (ENGINE-MIG-006)
9. POSTMVP-009 Fillet/Chamfer — superseded, делается после миграции
10. POSTMVP-010 Patterns/Mirror — superseded, делается после миграции
11. POSTMVP-011 Hole Families — superseded, делается после миграции
12. POSTMVP-012 Boolean/Multi-body — superseded, делается после миграции
13. POSTMVP-013 P2 Golden Corpus — после миграции
14. POSTMVP-014 P2 Reliability Gate — после миграции

Не объединять весь список в один Codex run.

## 9. Смена движка

Пункты 9–14 выше **отменены в том виде, в каком они написаны**: они
предполагают КОМПАС. Движок переходит на build123d/OpenCascade —
`docs/adr/ADR-023-build123d-replaces-kompas.md`.

Причина не в адаптере, который работает, а в том, чего он требует: Windows,
лицензия на каждую машину, GUI-приложение, которым управляют из программы, и
константы, которые можно узнать только измерением, потому что библиотеки типов
не экспортируют ни одного перечисления.

Порядок работ — ENGINE-MIG-001 … 008:

1. **ENGINE-MIG-001** — ADR, отказ от КОМПАС и M3D, обновление документов. Сделано.
2. **ENGINE-MIG-002** — нейтральные контракты движка, `packages/cad-engine-contracts`. Сделано.
3. **ENGINE-MIG-003** — доверенный build123d worker на Linux, в контейнере. Сделано.
4. **ENGINE-MIG-004** — ограничения и селекторы на новой модели топологии. Сделано.
5. **ENGINE-MIG-005** — независимая проверка STEP и STL после экспорта. Сделано.
6. **ENGINE-MIG-006** — паритет на существующих фикстурах, плюс revolve. Сделано:
   `docs/acceptance/ENGINE-MIG-006-fixture-parity.md` и `-revolve.md`, CAD-IR 1.4,
   `docs/adr/ADR-024-*`.
7. **ENGINE-MIG-007** — интеграция сервиса с новым worker. Сделано:
   `docs/acceptance/ENGINE-MIG-007-service-integration.md`. Долг шестого шага
   закрыт — у движка есть свои capability и per-operation флаги (ADR-021).
8. **ENGINE-MIG-008** — переключение и удаление КОМПАС. Сделано:
   `docs/acceptance/ENGINE-MIG-008-kompas-removed.md`.

Миграция завершена. Дальше — операции, к которым дорожная карта и шла, уже на ядре,
которое их документирует: fillet/chamfer, patterns/mirror, hole families,
boolean/multi-body, golden corpus, reliability gate; sweep/loft/shell — после
стабилизации базовых операций.

Два хвоста от миграции, оба названы в приёмочном документе: `KOMPAS_BUILD`,
`KOMPAS_STARTUP` и `kompas_version` живы, потому что их пишут уже сохранённые
строки, и уходят, когда таких строк не останется; и ни один деплой ещё не работал
на образе контейнера.

Реализация КОМПАС удаляется только на последнем шаге и только после приёмки
предыдущих: удалять единственный работающий движок до того, как замена
доказана, — это способ превратить миграцию в простой.

После миграции операции возобновляются уже на build123d, в прежнем порядке:
fillet/chamfer, patterns/mirror, hole families, boolean/multi-body, golden
corpus, reliability gate; sweep/loft/shell — отдельными задачами после
стабилизации базовых операций.
