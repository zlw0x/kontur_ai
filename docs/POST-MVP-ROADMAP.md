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

1. Деплой на образе контейнера — единственный незакрытый хвост миграции.
2. Операции: fillet/chamfer (сделано), patterns/mirror (сделано),
   boolean/multi-body (сделано); hole families — не отдельной операцией.
3. Golden corpus (POSTMVP-013) и reliability gate (POSTMVP-014) — сделано.
4. Калибровка тарифного профиля — он до сих пор поставляется с нулевыми ставками.

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
