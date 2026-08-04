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

Разбор — `docs/GATE-P4-ANALYSIS.md`: обе половины гейта закрыты наполовину, и не теми
половинами, которые следуют из формулировки. Соответствие сечений: правило «один вид, одно
число вершин» (ADR-031) закрывает неоднозначность, дающую **залом**, и оставляет открытой
ту, что даёт **симметрию** — квадрат, повёрнутый на 90°, это тот же квадрат, и документ,
заявивший поворот, получает призму без поворота (48 000.0000 мм³, ровно как у неповёрнутой).
Оракул: сквозная проверка рода по STEP и по STL работает на каждой сборке, а *заявленную*
топологию несут 16 случаев из 59 — и ни один из них не sweep и не loft. Замкнутые формулы
для обоих выведены и проверены на трёх точках каждая.

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
9. POSTMVP-009 Fillet/Chamfer — сделано на build123d (CAD-IR 1.5, ADR-026)
10. POSTMVP-010 Patterns/Mirror — сделано на build123d (CAD-IR 1.6, ADR-027)
11. POSTMVP-011 Hole Families — **не делается как отдельная операция**: всё выражается композицией (см. ниже)
12. POSTMVP-012 Boolean/Multi-body — сделано на build123d (CAD-IR 1.7, ADR-028)
13. POSTMVP-013 P2 Golden Corpus — сделано (42 positive / 16 negative)
14. POSTMVP-014 P2 Reliability Gate — сделано, вместе с 013

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

## 10. Полный цикл: изображение → ИИ → CAD-IR → модель

Миграция закончилась движком, который умеет больше, чем у него просят. Дальше —
то, что мешало циклу работать целиком, а не следующая операция.

### POSTMVP-015 — Shape Claim. Сделано

`docs/acceptance/POSTMVP-015-shape-claim.md`, `docs/adr/ADR-025-*`.

Все проверки в конвейере были проверками документа против самого себя, поэтому
неверно прочитанный контур давал валидный документ, который собирался в точную,
manifold и **не ту** деталь — и сказать об этом было нечем.

Стадия чтения теперь заявляет, **чем деталь является**, до того как появится
геометрия: контур, отверстия по видам и количеству, число тел, id параметра
толщины. Доверенный код (`cad_ir/shape_claim.py`) сравнивает с этим скомпилированный
CAD-IR; `validate --claim` отдаёт типизированные расхождения, на которые реагирует
цикл ремонта. Claim несёт виды и количества и **никогда не координату** — размер
проверяет expectation против числа с чертежа.

Побочный итог: оба промпта перестали называть один класс формы. Промпт анализа
просил «один центрированный прямоугольник и круглые отверстия» — геометрию MVP,
вписанную в инструкцию, тогда как движок давно строит слоты, полигоны, дуги,
острова, бобышки и revolve. Узким местом был промпт, а не ядро.

Что осталось открытым — там же: вопрос с `parameter_id: "shape"` имеет смысл и место
в промпте, но ни один прогон его ещё не выдал, и это требует реального Codex на
доверенной машине; `closed_profile` — то, куда попадает контур вне четырёх названных
видов, и о нём проверка говорит только число тел, отверстий и толщину.

### Дальше по этому же циклу

1. Деплой на образе контейнера — сделано,
   `docs/acceptance/ENGINE-MIG-DEPLOY-image-on-a-real-daemon.md`.
2. То, что цикл вообще имеет право сказать (POSTMVP-016) — контракт сделан, прогоны
   должны.
3. Операции: fillet/chamfer (сделано), patterns/mirror (сделано),
   boolean/multi-body (сделано), shell (POSTMVP-017, сделано); hole families — не
   отдельной операцией.
4. Golden corpus (POSTMVP-013) и reliability gate (POSTMVP-014) — сделано.
5. Sweep и loft (POSTMVP-018, сделано).
6. Rib и draft (P3.2, P3.3); по Gate P4 — два небольших куска достижимы сейчас
   (`docs/GATE-P4-ANALYSIS.md`), дальше стена P4.3 — 3D-кривые.
7. Калибровка тарифного профиля — он до сих пор поставляется с нулевыми ставками.

### POSTMVP-009 — Fillet/Chamfer. Сделано

`docs/acceptance/POSTMVP-009-fillet-chamfer.md`, `docs/adr/ADR-026-*`, CAD-IR 1.5.

Первые операции, которые ничего не строят. Всё до них брало профиль и делало
материал — ошибка давала тело неверного объёма, и её ловила арифметика. Blend
меняет рёбра, которые назвал селектор, поэтому его отказ выглядит как **деталь
точно нужного размера со скруглением не там**: габарит плиты с округлёнными углами
равен габариту плиты, тел по-прежнему одно, счётчик отверстий об углах не знает.

Отсюда три правила, которые наследует любая операция того же рода:

- blend **не может объявить cardinality, допускающую ноль совпадений**: `all` и
  `zero_or_one` превращают «не нашёл ни одного ребра» в успешную фичу;
  «скруглить все четыре угла» пишется `exactly_n: 4`, и тогда пятый угол —
  противоречие, а не неожиданность;
- асимметричный chamfer **называет грань, от которой отмерена первая длина**, иначе
  сторону выбирает ядро;
- blend **невидим для shape claim** — скругление не меняет, *чем деталь является*, —
  и ровно поэтому появилось ожидание `surface_face_count`: единственная проверка,
  которая видит fillet.

Заодно закрыты две дыры в селекторах: `convexity` теперь измеряется (с ADR-019 её
молча игнорировали, и селектор брал и выпуклые, и вогнутые рёбра), а предикат,
который движок посчитать не может (`produced_by`), отвергается кодом
`SELECTOR_UNSUPPORTED_PREDICATE`. Seam-рёбра исключаются резолвером с записью в
trace.

Обе операции объявлены `experimental` — не потому, что не работают, а потому, что
сервис пока не может породить документ с ними: shape claim не имеет слова для
скругления, значит стадия чтения его не заявит и сравнивать blend будет не с чем.
Это тот же разрыв, что у revolve, и он про зрение, а не про геометрию.

Measured, а не предположено: **chamfer ребра, которое упирается в fillet, заставляет
OpenCascade добавить коническую переходную грань на каждом таком углу**. Фикстура
переделана так, чтобы этого не было, вместо того чтобы расширять ожидание под
деталь ядра.

### POSTMVP-010 — Patterns/Mirror. Сделано

`docs/acceptance/POSTMVP-010-patterns-mirror.md`, `docs/adr/ADR-027-*`, CAD-IR 1.6.

Шесть отверстий по окружности выражались и раньше — шестью контурами с шестью
наборами координат. Паттерн добавляет не геометрию, а то, что **количество становится
тем, что документ заявляет**: шесть координат — это шесть шансов ошибиться и нечего
сравнить, а «шесть, через 60°, вокруг этой оси» — одно намерение, и с ним можно
сравнить shape claim, прочитанный с чертежа.

Поэтому паттерн — первая операция после ADR-025, которую стадия чтения реально может
попросить: «шесть круглых отверстий» чертёж показывает, а скругление угла claim
назвать не умеет.

Решения: паттерн называет **фичу**, а не результат; instance 0 — собственное место
источника, поэтому паттерн шести добавляет пять; шаг **заявляется**, а не делится из
полного угла; пропуск задаётся порядковым номером, и это не индекс геометрии, потому
что нумерацию задаёт сам документ; **сетка — это паттерн паттерна**, отдельной
операции нет. Движок переиспользует тот же tool-maker, которым строил источник, так
что повторение операции *является* этой операцией.

Самая ясная иллюстрация того, зачем нужен shape claim: **12 экземпляров через 60° —
это шесть отверстий, просверленных дважды**. Деталь совпадает с правильной, объём,
счёт граней и род поверхности сходятся — и только claim, сравнивающий заявленные
количества, это замечает.

Побочно найден дефект слоя селекторов, живший с POSTMVP-005: `centroid` дескриптора
брался из `center()` build123d, а это `CenterOf.GEOMETRY` — точка **на** поверхности
для всего кривого. Центр Ø8 отверстия при x = −50 читался как x = −54. Ничего не
падало: документ, выбирающий «грань с центром x = −50», просто не находил её. Теперь
центр масс, с регрессионным тестом.

### POSTMVP-011 — Hole Families. Не делается как отдельная операция

Всё, что перечислено в P2.3, уже выражается композицией: сквозное отверстие — это
`cut.extrude` с `through_all`, глухое — с `distance`, зенковка и зацентровка — chamfer
кромки (POSTMVP-009), серия — pattern (POSTMVP-010), отверстие на грани — sketch на
face-селекторе, отверстие «по координатам» — координаты контура.

Отдельный тип `feature.hole` был бы **вторым способом сказать то, что CAD-IR уже
говорит**, а каждый лишний тип в контракте — это лишнее, что надо валидировать, лишний
путь в движке и лишний набор фикстур. По-настоящему не хватает только резьбы, и это
производственная пометка, а не геометрия: настоящая геометрия резьбы уже вынесена
роадмапом в отдельную advanced capability.

### POSTMVP-012 — Boolean/Multi-body. Сделано

`docs/acceptance/POSTMVP-012-boolean-multi-body.md`, `docs/adr/ADR-028-*`, CAD-IR 1.7.

`source_body` жил в контракте с 1.1, и движок его игнорировал — потому что тело было
одно. Теперь тело **создаётся по имени** (`new_body`, обязан назвать свой `produces`),
**адресуется по имени** и **комбинируется по имени** через `feature.boolean`
(union/subtract/intersect, `keep_tools`). Фича, которая не сказала ничего, работает с
**активным телом** — последним созданным или изменённым, — и именно поэтому для всех
документов до 1.7 ничего не изменилось.

Что это включило: `from_result` у селектора наконец что-то решает (фаска на теле,
которое назвал селектор, не трогает соседнее), `body_count` наконец может быть не 1,
несколько тел уходят в STEP компаундом, а не сплавляются молча.

Решение по claim — самое крупное на сегодня: **вычтенное тело-инструмент это отверстие,
а не кусок металла**. С булевыми операциями «чем деталь является» больше нельзя прочесть
по типам фич. `solids` (сколько кусков считает человек по чертежу) и `body_count`
(сколько тел в файле) остаются разными вопросами — фикстура заявляет два тела и
удовлетворяет claim о трёх solids.

Найден дефект верификатора, который жил бы дальше: `_genus` считал формулу Эйлера для
**одной** замкнутой поверхности. Для двух тел с одним сквозным отверстием получался
genus 0, а для двух тел без отверстий получилось бы **−1** — отрицательное число
отверстий на совершенно правильной детали. Теперь число компонент считается union-find
по сетке.

### POSTMVP-013/014 — Golden Corpus и Reliability Gate. Сделано

`docs/acceptance/POSTMVP-013-014-golden-corpus.md`.

**42 положительных случая и 16 отрицательных**, генерируемых подстановкой чисел в формы
документов. Каждое ожидаемое число — замкнутая формула с чертежа (плита `w·h·t`,
отверстие `π r² t`, n-угольник `½ n R² sin(2π/n)`, паз `π r² + 2 r L`, фаска
`π(R d² + d³/3)`, частичный revolve — доля оборота), поэтому случай не может пройти
за счёт того, что движок согласен сам с собой.

Гейт (`test_corpus.py`, 70 тестов, в обычном прогоне) проверяет: каждый положительный
случай собирается и верифицируется; измеряется ровно та арифметика; каждый отрицательный
отвергается **именно тем кодом**, который назвал, и не оставляет файлов; семь случаев
собираются дважды и сравниваются побайтово; корпус покрывает **каждую** capability,
которую движок объявляет.

Детерминизм измерен, а не предположен: **STL побайтово идентичен**, STEP отличается ровно
одной строкой из 415 — `FILE_NAME` с таймстампом, который OpenCascade пишет в каждый файл.

**Три дефекта, которые нашёл корпус:**

1. остров, целиком лежащий **вне** контура, молча игнорировался — существующая проверка
   ловит остров, который съедает профиль или разрезает его, а промахнувшийся оставляет
   ровно один регион ровно той же площади. Движок собирал плиту без отверстия и сообщал
   об успехе. Теперь `SKETCH_ISLAND_OUTSIDE_PROFILE`;
2. сравнение сетки с телом было строже, чем формат, который оно читает: STL хранит
   float32, и высота треугольной плиты 20√3 = 34.641016151377546 сохраняется как
   34.64101791381836 — на 1.76e-6 мм **больше**. Допуск был 1e-6. Теперь — два ulp
   наибольшего габарита;
3. сохранённый перекрывающийся инструмент — **не** один манифолд, и это правильный ответ:
   два тела делят грань, по которой шёл вырез. Случай вынесен в отдельный тест, а не
   допущен в корпус, потому что иначе пришлось бы ослабить проверку, которая после этого
   перестала бы видеть любую рваную сетку.

**Продвижение:** 32 ключа переведены из `experimental` в `beta` — revolve, оба blend'а,
все три паттерна, mirror, именованные тела, все три булевых, convexity,
`validate.surface_face_count`. `experimental` значит «API не выдаёт лизу на работу,
которой это нужно», так что именно это продвижение делает операции доступными через
ручной API. Не продвинут один: `feature.chamfer.asymmetric` — корпус не варьирует его
единственный содержательный вопрос (от какой грани отмерена первая длина).

Чего это **не** является: это не Gate P2 (100 моделей / 30 типов / 99% на synthetic
corpus), и ничего не объявлено `stable`. И это не проверка работы воркера с процессами —
«100 последовательных E2E без утечки процессов» относится к запуску контейнеров.

### Контейнер: сделано на живом демоне

`docs/acceptance/ENGINE-MIG-DEPLOY-image-on-a-real-daemon.md`. Образ
(`apps/cad-worker/Dockerfile`) собран, `describe` под `--read-only --network none` отвечает
build123d 0.11.1 на OpenCascade 7.9.3.1.1 с 33 capabilities и ровно двумя артефактами,
`lever-plate` собирается через bind-mount с `verified true`, четыре контейнерных теста
лаунчера прошли с первого раза, и оба рантайма вместе дают **35 из 35 без пропусков** —
для процессного появилась `CAD_ENGINE_PYTHON`, симметрично `CAD_ENGINE_IMAGE`. Кода
контейнерная половина не потребовала вовсе. Ниже — то, что сделало это проверяемым, и
почему сборка не идёт в песочнице (сетевая политика, а не код; в песочнице пропуск
контейнерных тестов остаётся ожидаемым).

- `packages/build123d-launcher/tests/ContainerEngineTests.cs` — лаунчер против **живого**
  демона в том режиме, который использует production: манифест, сборка с результатами,
  вернувшимися из bind-mount'а, shape claim на своём read-only mount'е, и флаг оператора,
  соблюдённый внутри контейнера. Тесты пропускают себя, если `CAD_ENGINE_IMAGE` не назвал
  образ, поэтому suite остаётся запускаемым везде.
- CI-job `cad-worker-image` собирает образ и **выставляет `CAD_ENGINE_IMAGE`**, так что эти
  тесты идут там же, где образ существует. Заодно в job'е исправлено устаревшее: фикстура
  была `lever-plate.v1_4.json`, а проверка объявляла `solid.revolve` как `experimental` —
  после корпуса это `beta`, и утверждение теперь про «лизуемость», а не про конкретную
  ступень.

Почему сборка не прогнана в этой песочнице — сетевая политика, а не код:

| хост | зачем | ответ прокси |
|---|---|---|
| `registry-1.docker.io`, `auth.docker.io` | метаданные образа | 401/404 (доступны) |
| `production.cloudfront.docker.com` | блобы Docker Hub | **403 на CONNECT** |
| `mirror.gcr.io` | зеркало Docker Hub | доступно — базовый образ качается через него |
| `pypi.org`, `files.pythonhosted.org` | колёса build123d/OCP | в `noProxy`, доступны (внутри контейнера нужен CA прокси) |
| `deb.debian.org`, `ftp.debian.org`, `cloudfront.debian.net` | libGL и прочие .so | **403 на CONNECT, все** |

Базовый образ и слой pip воспроизводятся; слой `apt-get install` — нет, потому что закрыты
все хосты пакетов Debian.

Заодно **эмпирически подтверждено, что apt-слой обязателен**, а не перестраховка: образ,
собранный без него (base + pip + код), падает на `import build123d` с
`ImportError: libGL.so.1: cannot open shared object file` — ровно первая библиотека из
списка в Dockerfile, и ровно то, что говорит комментарий над ним про headless-сборку
OpenCascade.

### POSTMVP-016 — что цикл вообще имеет право сказать. Контракт сделан, прогоны должны

`docs/acceptance/POSTMVP-016-what-the-cycle-may-state.md`, `docs/adr/ADR-029-*`.

Движок объявляет 33 capability. Цикл «чертёж → модель» дотягивался до двух: плита на XY
и сквозные отверстия. Всё, что построено после миграции, было доступно только через
ручной CAD-IR. Разрыв — не недосмотр и **не одна причина**, и пока причины не разделены,
соблазн один: расширять профиль, пока что-нибудь не сломается.

Три стены держат разные операции:

- **диалект** — в structured output у Codex нет необязательных свойств: каждый объект
  обязан перечислить все. Операция, у которой вход честно опционален, невыразима — модель
  вынуждена выдать поле, а канонический валидатор потом это отвергнет;
- **claim** — если стадия чтения не может назвать вещь, то её постройку никто не
  проверяет: `disagreements` нечего сравнивать. Отдать операцию, которую claim не видит, —
  обменять узкий-но-проверенный цикл на широкий-но-непроверенный;
- **зрение** — увидит ли агент эту фичу на скане. Единственная из трёх, которую нельзя
  закрыть кодом здесь.

Профиль вырос ровно до того, что claim уже умеет проверять, — четыре формы, у каждой все
поля обязательны: **глухой вырез** (`through_all: false` плюс `distance` — отдельной
ветвью, потому что контракт запрещает сказать и то и другое, а диалект не умеет
«необязательно»; две ветви удовлетворяют обоим правилам сразу), **datum-плоскость и
бобышка на ней**, **линейный и круговой паттерн**. Геометрия не новая — всё это уже строят
случаи корпуса; новое в том, что этого может *попросить цикл*.

Вместе с глухим вырезом обязана была прийти проверка: `OpeningClaim.through`. Пока всё,
что цикл умел, шло насквозь, глубину нельзя было прочесть неверно. Как только документ
может остановить отверстие внутри материала, неверно прочитанная глубина — это валидный
документ, который собирается и измеряет ровно то, что заявил, включая собственный
`through_hole_count`. **Ничего — это не «false»**: читатель, который не разобрал глубину,
говорит `null`, и claim, который молчит, согласен с любой. Проверка существует ради
чертежа, где карман виден явно, а не ради наказания за честное «не видно».

Промпты выросли вместе с профилем — и один из них нашёл дефект. Промпт компиляции —
raw string literal, в котором расписан вложенный JSON, поэтому в тексте встречается `}}`
и ему нужен `$$$` там, где остальным хватает `$$`. Ошибка в уровне интерполяции **не
ломает сборку**: она рендерит `{1.7}` вместо `1.7` или буквальные `{{CadIrVersion}}`.
Увидеть это можно только в прогоне ИИ — в самом дорогом месте. Теперь тест рендерит все
промпты через конвейер и требует, чтобы ни один плейсхолдер не дожил до модели.

Что осталось за стенами и за какой: fillet/chamfer — за диалектом **и** за claim
(предикаты селектора опциональны, а у claim нет слова для скругления); revolve — за claim
и за зрением; булевы и именованные тела — выразимы, но чертёж их не показывает; селекторы
граней — за диалектом.

**Контракт — это не прогон.** Выдаст ли модель паттерн, увидев болтовую окружность, знает
только настоящий Codex, а он авторизован на доверенной машине. Здесь сделаны схема,
которой её ограничат, промпт, который сообщает ей об этих формах, claim, который проверит
ответ, и тесты на все три. Шесть прогонов, которые это закрывают, перечислены в приёмке.

### POSTMVP-017 — Shell (CAD-IR 1.8). Сделано

`docs/acceptance/POSTMVP-017-shell.md`, `docs/adr/ADR-030-*`.

Все операции до этой отвечают на вопрос «какой формы деталь». Shell отвечает на другой,
и вся ADR держится на одной таблице: корпус 100 × 60 × 40 со стенкой 3 мм и сплошной
блок того же размера совпадают по контуру, по отверстиям, по числу тел, по габаритному
ящику и по числу сквозных отверстий — и отличаются вчетверо по материалу. Ни одна
проверка, которую документ мог нести до сих пор, их не различает.

**Два измерения решили контракт**, и оба остались тестами, а не комментариями.

`offset` — это **две операции под одним именем**, и решает, какая именно, список
открытых граней:

| вызов | результат | что это |
|---|---|---|
| `offset(box, -3, openings=[top])` | 52 188 мм³, габарит не изменился | полая коробка |
| `offset(box, -3, openings=[])` | 172 584 мм³ = 94 × 54 × 34 | **сплошная, но меньше** |

Поэтому shell не имеет права объявить кардинальность, допускающую ноль совпадений — то
же правило, что у blend с ADR-026, но с более жёсткой причиной: селектор, не нашедший
ничего, не пропускает шаг, а молча подменяет деталь.

Стенка, для которой в детали нет места, **не вызывает ошибки**: 30 мм внутрь возвращают
исходное тело целиком, 240 000 мм³, и всё в документе это проходит. Движок сравнивает
объём до и после и отвергает с `SHELL_NO_CAVITY`. Предпроверкой это не ловится: 25 мм при
открытом верхе — нормальная стенка (полость 15 мм), при закрытом — нет, и знает об этом
только ядро.

Направление заявляется, а не берётся по умолчанию у ядра: те же грани, та же толщина и
деталь на 6 мм больше по x и y. Два ключа capability, `feature.shell.inward` и
`feature.shell.outward`, оба сразу `beta` — корпус варьирует всё, что операция решает
(две формы, две толщины, одна и две открытые грани, оба направления), а это и есть
критерий POSTMVP-013/014. Движок теперь объявляет **35 capability: 34 beta, 1
experimental**.

Не предлагается: стенка «по обе стороны» поверхности (в OCC такого режима нет, а собрать
её из двух offset'ов значит положить в документ размер, которого нет на чертеже) и выбор
типа перехода (`Kind.INTERSECTION` зафиксирован — `ARC` скруглил бы каждый внутренний
угол радиусом, которого никто не заявлял).

**Claim получил одно слово — `wall`**: id параметра, в котором лежит толщина стенки. Это
первое, что claim говорит о том, *сколько детали есть*, а не какой она формы, и правило
ADR-025 не нарушено: claim несёт имя параметра, никогда не число. Молчание по-прежнему не
заявление — читатель, не увидевший стенку, не противоречит документу, который её сделал.

**Цикл пока не может попросить shell, и порядок здесь намеренный**: вход операции — face
selector, то есть стена диалекта из ADR-029. Слово claim'а про полую деталь появляется
первым, выходной профиль подтянется, когда диалект позволит. В
`schemas/drawing-analysis.schema.json` ничего не добавлено по той же причине: claim,
который стадия компиляции не в состоянии удовлетворить, завалил бы каждый чертёж корпуса.

Фикстура `tests/fixtures/cad-ir/enclosure.v1_8.json` — 120 × 80 × 40, углы R10, стенка
3 мм с открытым верхом, два Ø6 под крепёж сквозь дно: fillet, shell, cut и pattern в одном
документе, объём замкнутой формулой сходится с точностью 6e-11. Деталь, которую стоит
назвать: смещение скруглённого контура внутрь на `t` оставляет дуги радиуса `R − t`, и в
готовом теле ровно те десять цилиндрических граней, которые это предсказывает — четыре
R10, четыре R7, два R3.

**Два дефекта версий, найденных по дороге**, оба одного рода — один факт, записанный
дважды, и им позволили разойтись. `MIGRATABLE_VERSIONS` содержал 1.6, а ветка нормализатора
— нет: валидатор говорил «сначала нормализуй», нормализатор отвечал «версия не
поддерживается», один и тот же билд на одном прогоне, и так с самого 1.7. Теперь набор
«только переклейка ярлыка» выводится из списка миграций, и тест проходит по каждой версии
в нём. И `generate_output_profile.py` держал версию CAD-IR литералом — профиль, прибитый к
версии, которую контракт уже перерос, заставлял бы модель выдавать документ, отвергаемый
валидатором целиком.

### POSTMVP-018 — Sweep и Loft (CAD-IR 1.9). Сделано

`docs/acceptance/POSTMVP-018-sweep-and-loft.md`, `docs/adr/ADR-031-*`.

Две операции в одной версии, потому что это один вопрос, заданный дважды: есть профиль —
что его несёт? Траектория или следующее сечение.

Отличие от всего, что было раньше: **неверный документ не падает громко**. Измерено пять
случаев, и все пять собираются:

| что говорит документ | что делает ядро |
|---|---|
| траектория из (30, 0, 0), профиль в начале координат | строит деталь **в начале координат** — позиция траектории игнорируется |
| Ø16 вдоль линии под 45°, длиной 56.57 | 8 042 мм³ = π·8²·**40**: подмело *проекцию* профиля, 1/√2 от нарисованного сечения |
| Ø16 вокруг изгиба R4 | собирается, `is_valid` = True, объём точно по Паппу; знает только сетка — **69 открытых рёбер** |
| два сечения loft в одной плоскости | одно замкнутое тело, объём **0.0** |
| квадрат в круг | тело правдоподобного объёма с соответствием, которое ядро выбрало и не назвало |

Отсюда решения. Траектория **задаётся от профиля** — начинается в начале координат своей
плоскости, потому что абсолютную позицию ядро всё равно не соблюдает, и число, которое
ничего не значит, рано или поздно значит что-то неверное. Она разомкнута, касательно
непрерывна (угол — это радиус изгиба, которого не дал чертёж; ядро на его месте выдумает
один из трёх ответов, а выдуманный радиус — ровно то, что ADR-026 запрещает blend'у) и
перпендикулярна профилю.

Проверка изгиба — **направленная**, а не по описанной окружности: профиль шириной 40,
смещённый на 15 от траектории, дотягивается на 35 в одну сторону и на 5 в другую, так что
изгиб R10 от массива материала — корректный документ, а к нему — нет. Единая проверка «а
влезает ли профиль в радиус» отвергла бы оба, то есть завернула бы правильный чертёж.

У loft'а **все сечения одного вида с одинаковым числом вершин** — это Gate P4 («неоднозначное
сопоставление сечений отклоняется») с другого конца. Побочный, но важный итог: claim'у не
нужно ничего нового — его `profile` и есть вид, которым является каждое сечение. Если бы
смешанные сечения были разрешены, claim «circle» удовлетворялся бы телом, которое
заканчивается квадратом.

Обе операции проверяемы, потому что у обеих замкнутая формула: **Паппа** для sweep
(`площадь × длина пути`, точно и на изгибах — центроид профиля лежит на траектории) и
**правило призматоида** для loft (`h/3 × (A₁ + √(A₁A₂) + A₂)`). Трёхсекционный `ruled` — это
два призматоида подряд, а гладкий — нет (37 632 против 49 920), и поэтому `ruled` заявляется,
а не берётся по умолчанию у ядра.

Восемь положительных случаев корпуса и семь отрицательных; `sweep-elbow` и
`loft-truncated-cone` добавлены в набор детерминизма. Четыре ключа — `solid.sweep`,
`cut.sweep`, `solid.loft`, `cut.loft` — сразу `beta`. Движок объявляет **39 capability: 38
beta, 1 experimental**.

Фикстура `transition-duct.v1_9.json` — квадратный раструб, сведённый loft'ом к горловине, и
горловина, поднятая sweep'ом и уведённая в изгиб. Обе операции в одном документе, и они
сплавляются без boolean: sweep не называет тело, значит присоединяется к строящемуся. Объём
164 342.9174 сходится с суммой двух замкнутых форм ровно.

Чего это **не** является: цикл не может попросить ни то, ни другое — но это стены *claim* и
*зрения* из ADR-029, а не стена диалекта (sweep прекрасно выразим в структурированном
выводе Codex; распознать осевую линию с радиусами изгиба на виде — задача зрения). 3D-путь
(P4.3) не входит: CAD-IR нечем сказать, где точка в пространстве, а плоская траектория — это
как раз то, что даёт чертёж. Направляющие кривые, контроль закрутки и повершинное
соответствие (P4.1/P4.2) — это то, как возвращаются отвергнутые случаи, и всё это должен
заявлять *документ*. И это не Gate P4: здесь арифметический оракул, а topology oracle —
следующее, что этой операции нужно.

### POSTMVP-019 — Именованные выборки: стена диалекта оказалась ниже. Сделано

`docs/acceptance/POSTMVP-019-named-selections.md`, `docs/adr/ADR-032-*`.

ADR-029 читал правило 4 диалекта («каждый объект перечисляет все свои свойства как
обязательные») так: селектор предложить нельзя, потому что его предикаты по отдельности
необязательны. Это верно для предикатного **словаря**. Правило 4 говорит о тех свойствах,
которые схема **объявляет**, и никто не обязывает профиль объявлять их все: `where` с тремя
предикатами, все три обязательны, — законен по диалекту **и** канонически валиден, потому
что опущенные необязательны в контракте. Три операции простояли за неверным прочтением
целую веху.

Теперь профиль предлагает **выборки**, а не селекторы: вертикальные выпуклые углы контура,
круглые кромки, крайние по Z, планарная грань с нормалью +Z. Каждый предикат — константа,
`from_result` — константа `body.main`, выбирать нечего, кроме количества. **Модель ничего
не составляет**, и это решение, а не побочный эффект: выборка написана здесь, против
топологии, которую строит этот движок, и покрыта корпусом; составленная моделью была бы
селектором, который никто никогда не разрешал на реальной детали.

За выборками пришли четыре операции — скругление углов, фаска углов, фаска кромки
отверстия и оболочка. И claim вырос вместе с ними, потому что правило ADR-029 режет в обе
стороны: отдать операцию, которую claim не видит, — обменять узкий-но-проверенный цикл на
широкий-но-непроверенный.

`ShapeClaim.blends` — вид и количество. Плита с острыми углами там, где на чертеже R5,
совпадает по контуру, отверстиям, числу тел и габариту; `surface_face_count` мог бы это
увидеть, но его пишет та же стадия, которая выбрала blend. Количество, никогда не радиус —
правило ADR-025 цело. Сравнивать количество можно только потому, что профиль выдаёт
`exactly_n`, а это единственная кардинальность, которую разрешает ADR-026; рукописный
`one_or_more` числа не назвал, и claim с ним не спорит. И `wall_parameter` наконец дошёл до
стадии чтения — цикл теперь умеет построить оболочку, которую он описывает.

Цикл дотягивается до **десяти** capability движка из 39 вместо шести. Всё, что claim умеет
проверить, предложено, и **зрение осталось единственной стеной, которая имеет значение**:
revolve, sweep, loft и булевы ждут ответа на вопрос, различит ли агент их на скане, — а
этого не решает никакой код здесь.

Промпт нашёл тот же дефект уровнем глубже: выборка, выписанная дословно, даёт `}}}`, а это
терминатор интерполяции при `$$$` — не компилируется. Поднимать до `$$$$` значило бы
сломаться на следующем вложенном объекте, поэтому закрывающие скобки в примерах вынесены на
отдельные строки; тест рендеринга промптов из POSTMVP-016 делает такое форматирование
руками безопасным.

**Что дальше — прогоны.** Их девять: шесть в приёмке POSTMVP-016 и три новых (плита с R5 по
четырём углам, кромка с «2×45°», корпус с толщиной стенки). Пока их нет, любое дальнейшее
расширение — догадка.

### POSTMVP-020/021 — Топологический оракул и режимы выдавливания (CAD-IR 1.10). Сделано

`docs/acceptance/POSTMVP-020-021-topology-oracle-and-extrusion-modes.md`, `docs/adr/ADR-033-*`.

**Оракул.** Gate P4 просит проверку структуры результата, а не размера. Препятствие
выглядело так: чертёжный агент никогда не назовёт число граней — с чем сравнивать? Ответ:
результат сравнивается **сам с собой**. Каждая сборка отдаёт STEP и STL, написанные двумя
разными экспортёрами, и род поверхности (сколько у тела «ручек») считается по любому из
них — Эйлера–Пуанкаре по B-rep, Эйлера по треугольникам. Ни одно из чисел не приходит из
документа, поэтому проверке нечего требовать заявленным и её нельзя удовлетворить тем, что
план согласен сам с собой. Работает на каждой сборке.

Член `L` — вот почему это работает и почему прошлая попытка сдалась: наивное
`V − E + F = 2 − 2G` даёт 0 для плиты, в которой явно есть отверстие, потому что B-rep
считает полную окружность одним ребром с одной вершиной. Считать надо **контуры**, и у
грани с отверстием их два. Что оракул ловит: самопересекающийся sweep — STEP говорит
«аккуратное тело рода 0», STL говорит «род −45, 69 открытых рёбер», и по отдельности ни
одна половина не выглядит неверной.

Корпус заявляет `(грани, рёбра, вершины)` там, где чертёж это решает, — замкнутой формулой,
как объём: коробка это 6/12/8, а каждое круглое сквозное отверстие добавляет **одну грань,
три ребра и две вершины** — две окружности и шов, который OpenCascade кладёт на замкнутый
цилиндр. Шов из записанной цены миграции (ADR-023) стал числом, которое читает проверка.

**Режимы выдавливания.** `both_directions` заявляет **полную** длину и делит её пополам —
то же прочтение, что у revolve с 1.4; иначе деталь вышла бы вдвое толще, а заявленный
параметр толщины называл бы её половину. `taper_deg` сужает выдавливание по ходу
`direction`: плюс сужает, минус расширяет, и это единственное правило. Сделать его «уклоном»
значило бы, чтобы движок переворачивал знак для выреза, — а знак, которого документ не
видит, это знак, который выбрал кто-то другой. Формованный карман пишет отрицательный уклон
явно. Арифметика — правило призматоида, точно до шестого знака.

Слишком крутой уклон **не падает**: пятачок 20 × 20 с уклоном 45° на 40 мм возвращается
пирамидой высотой 10 — сечение закрывается на 10, ядро останавливается и сообщает об одном
валидном теле правдоподобного объёма. Теперь `EXTRUDE_DRAFT_TOO_STEEP`.

**Общий вывод, который стоит отдельно.** Это третья находка одной формы за три вехи:
**режим отказа этого ядра — правдоподобный ответ**. Оболочка без места возвращает исходное
тело; sweep вокруг слишком тесного изгиба — самопересекающееся; уклон за точкой смыкания —
огрызок. Все три сообщают о себе как о валидных. Поэтому **каждая операция, которую можно
пережать, получает пост-проверку результата против того, что просили**: предпроверке
пришлось бы предсказывать ядро, а знает только ядро.

Ни один из режимов не предложен циклу: симметрия и уклон — это выбор моделирования, а не то,
что чертёж говорит словами, которые есть у стадии чтения. Оракулу предлагать нечего вообще —
он работает на каждой сборке, включая те, что цикл уже делает.

**Дополнение (2026-08-04): у claim появилось слово для уклона.**
`docs/acceptance/POSTMVP-021-draft-in-the-claim.md`, поправка к ADR-033. `ShapeClaim.draft`
называет параметр, который держит угол, — и это самая незаметная из потерь, найденных до
сих пор: **сужающийся** уклон оставляет эскиз самым широким сечением, поэтому документ,
который его выронил, согласен с чертежом про контур, отверстия, число тел **и про
габаритный ящик**, а материала в нём на треть меньше (20 × 20 × 10 даёт 2 720.752 мм³
против 4 000). Ожидание объёма это видит — но ожидание объёма пишет та же стадия, что
выбрала уклон. Claim говорит имя и не говорит направление, и это **измерено**: плюсовой
уклон сужает прочь от плоскости эскиза в обе стороны хода, так что `direction` его не
переворачивает, а канонический `Scalar` (`float | ParameterRef`, без арифметики) не может
сменить знак у того, что ему дали. Заявленное «сужается» могло бы разойтись только с
собственным числом стадии чтения, а стадия, сверенная с собой, — не проверка (ADR-018).
Одно следствие всё же оставлено проверкой: названный угол, который держит **0°**, — это
вертикальные стенки с именем, и он отвергается.

Предложение циклу по-прежнему закрыто, но теперь **стеной зрения**, а не словарём claim:
уклон на чертеже — это угол со стрелкой на разрезе, и прочитает ли его агент со сканера —
вопрос прогона, а не кода. Про `both_directions` сказанное выше остаётся в силе.

Движок объявляет **42 capability** (41 beta), корпус — **59 положительных и 31
отрицательный** случай, 16 из них заявляют топологию.
