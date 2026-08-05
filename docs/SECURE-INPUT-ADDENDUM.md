# Дополнение: безопасная обработка входных чертежей

Статус: **растровый контур реализован** (2026-08-04); PDF-контур — нет.  
Дата решения: 2026-07-30.

## 0. Что построено, а что нет

| | статус |
|---|---|
| PNG/JPEG: quarantine → sanitizer → канонический PNG → manifest | **сделано** |
| потоковое чтение с подсчётом байтов и SHA-256 вместо `request.body()` | **сделано** |
| полное декодирование, EXIF orientation, alpha на белый, удаление metadata | **сделано** |
| ограничение списка декодеров самим sanitizer | **сделано** |
| лимиты: размер, ширина/высота, пиксели, время, память, CPU | **сделано** |
| изолированный процесс с `RLIMIT_AS`, `RLIMIT_CPU` и стенными часами | **сделано** |
| контейнерный режим (network none, read-only, cap-drop ALL, no-new-privileges, memory/CPU/PID) | argv собран и проверен тестом; образ не собран |
| worker и Codex получают только очищенный PNG | **сделано** |
| raw удаляется сразу после обработки | **сделано** |
| WEBP | нет: статичность — вопрос к декодеру, а формат без этой проверки принят по ошибке |
| PDF, растеризатор, tiles, overview | нет: отдельный контур, отдельный threat model |
| immutability на уровне БД и object storage | нет: состояние заказов ещё не в PostgreSQL (P0-4) |

Реализация: `packages/image-sanitizer` (декодер, отдельный пакет и отдельный
процесс), `apps/api/app/input/` (policy, quarantine, запуск), тесты —
`packages/image-sanitizer/tests/test_sanitize.py` и
`apps/api/tests/test_secure_input.py`.

## 1. Принятое решение

Публичный сервис принимает только:

```text
PNG
JPEG
WEBP
PDF
```

DXF, DWG, TIFF, SVG, GIF, APNG, BMP, HEIC/HEIF, PSD, ICO, архивы и
исполняемые файлы не входят в утверждённый входной контур.

Расширение списка форматов является отдельным архитектурным изменением и
требует собственного threat model, sandbox и acceptance-набора.

Главный инвариант:

> Codex, local worker, браузерное превью и КОМПАС получают только очищенные
> канонические PNG-страницы. Исходный загруженный файл не пересекает эту
> границу доверия.

## 2. Два независимых контура обработки

### 2.1. Растровые изображения

```text
PNG / JPEG / WEBP
  -> private quarantine
  -> потоковая проверка размера и SHA-256
  -> проверка сигнатуры
  -> isolated image sanitizer
  -> полное декодирование пикселей
  -> применение EXIF orientation
  -> сведение прозрачности на белый фон
  -> удаление metadata
  -> повторное кодирование в PNG
  -> immutable page manifest
  -> accepted storage
```

WEBP разрешён только как статическое однокадровое изображение. Animated WEBP
отклоняется.

Sanitizer обязан ограничивать список декодеров разрешёнными форматами. Одной
проверки `Content-Type`, расширения, magic bytes или `Image.verify()` недостаточно:
необходимы полный `load()` и создание новой pixel-only копии.

Прозрачность не переносится в канонический результат. RGB-данные под прозрачным
alpha-каналом не должны сохраняться.

### 2.2. PDF

```text
PDF
  -> private quarantine
  -> потоковая проверка размера и SHA-256
  -> PDF preflight
  -> isolated PDF rasterizer
  -> независимая растеризация каждой страницы
  -> pixel/dimension/page limits
  -> canonical PNG per page
  -> immutable document + page manifest
  -> accepted storage
```

PDF не обрабатывается общим image sanitizer и не передаётся ImageMagick с
автоматическими Ghostscript delegates. Используется один закреплённый PDF
rasterizer в отдельном контейнере или эквивалентно ограниченном процессе.

Rasterizer:

- не имеет сети;
- не имеет доступа к worker credential, Codex auth, БД и исходному коду;
- читает только один quarantine object;
- пишет только в выделенный output;
- запускается непривилегированным пользователем;
- имеет read-only root filesystem;
- работает с `cap_drop: ALL` и `no-new-privileges`;
- ограничен по памяти, CPU, PID, диску и времени;
- уничтожается после завершения или timeout.

Отклоняются:

- зашифрованные или защищённые паролем документы;
- повреждённые документы;
- документы с недопустимым числом страниц;
- страницы с некорректными или чрезмерными размерами;
- документы, не завершившие обработку за установленное время.

JavaScript, XFA, формы, мультимедиа, вложения, ссылки и внешние ресурсы не
переносятся в результат. Rasterizer не имеет сети и не должен выполнять
внешние delegates. Обнаруженные активные возможности фиксируются в audit и
могут быть основанием для отклонения согласно версии policy.

## 3. Начальные ресурсные лимиты

Лимиты являются versioned policy и уточняются по результатам нагрузочных
испытаний. Начальные значения:

```text
MAX_UPLOAD_BYTES             = 25 MiB
MAX_PDF_PAGES                = 10
MAX_IMAGE_FRAMES             = 1
MAX_PAGE_WIDTH               = 12 000 px
MAX_PAGE_HEIGHT              = 12 000 px
MAX_PAGE_PIXELS              = 60 000 000
MAX_SANITIZED_PAGE_BYTES     = 40 MiB
MAX_SANITIZED_DOCUMENT_BYTES = 160 MiB
SANITIZER_MEMORY             = 768 MiB
SANITIZER_CPUS               = 2
SANITIZER_PIDS               = 64
DOCUMENT_TIMEOUT             = 60 s
PAGE_TIMEOUT                 = 10 s
```

Ограничение применяется на всех уровнях:

- reverse proxy;
- API во время фактического потокового чтения;
- storage quota;
- sanitizer/rasterizer;
- accepted document;
- worker manifest и повторная проверка после скачивания.

`Content-Length` используется только как быстрый предварительный фильтр.
Фактически принятые байты считаются независимо, включая chunked transfer.

## 4. Качество PDF и крупных листов

Цель растеризации — сохранить тонкие линии, размерные надписи и выноски.

- базовое качество соответствует 300 DPI;
- ориентация и пропорции страницы сохраняются;
- фон результата белый;
- JPEG-сжатие канонических страниц запрещено;
- browser preview создаётся отдельно и не заменяет master page;
- уменьшение не должно делать мелкие размеры нечитаемыми.

Для страницы, которую нельзя безопасно передать анализатору целиком, создаются:

```text
page-001-overview.png
page-001-tile-001.png
page-001-tile-002.png
...
```

Overview имеет максимальную сторону 4096 px. Tiles имеют размер 2048 px и
перекрытие 128 px. Manifest хранит координаты каждого tile относительно master
page. Worker получает overview и tiles в подтверждённом порядке.

Master page остаётся источником координат. Масштабирование overview или tiles
не меняет подтверждённые размеры и геометрические координаты.

## 5. Quarantine и жизненный цикл

Состояния входного файла:

```text
UPLOADING
QUARANTINED
SANITIZING
ACCEPTED
REJECTED
DELETED
```

Правила:

- объект создаётся только под серверным UUID;
- пользовательское имя не участвует в filesystem/object key;
- существующий `file_id` нельзя заменить;
- повторная загрузка создаёт новую версию;
- job создаётся только после `ACCEPTED`;
- raw недоступен пользователю, worker и Codex;
- browser preview использует только sanitized PNG;
- raw удаляется после завершения обработки, но не позднее одного часа;
- для audit сохраняются хеш, размер, policy version, результат и typed-код;
- rejected storage не используется как бессрочное хранилище.

Запись `ACCEPTED` неизменяема на уровне БД и object storage, а не только по
соглашению в коде. Новая обработка создаёт новый manifest и новую версию.

## 6. Manifest

Минимальный document manifest:

```json
{
  "manifest_version": "2.0",
  "file_id": "uuid",
  "order_id": "uuid",
  "file_version": 1,
  "status": "ACCEPTED",
  "source": {
    "format": "PDF",
    "sha256": "hex",
    "size_bytes": 123456
  },
  "pages": [
    {
      "page": 1,
      "sha256": "hex",
      "size_bytes": 234567,
      "format": "PNG",
      "width": 7016,
      "height": 4961,
      "object_key": "accepted/sha256/page-001.png"
    }
  ],
  "sanitizer": {
    "name": "pdf-rasterizer",
    "version": "pinned-version",
    "policy_version": "secure-input-1"
  }
}
```

Worker manifest содержит только sanitized pages, overview/tiles при наличии,
их SHA-256, размеры, порядок и фиксированный `file_version`.

Worker после скачивания повторно проверяет:

- lease ownership;
- `file_id` и `file_version`;
- число и порядок страниц;
- размер каждого файла;
- SHA-256 каждого файла;
- разрешённое локальное имя;
- формат PNG.

Любое несовпадение завершает job typed-ошибкой до вызова Codex.

## 7. Prompt injection

Повторное кодирование не удаляет текст, нарисованный в пикселях. Любая надпись
в чертеже остаётся недоверенными инженерными данными.

Сохраняются обязательные ограничения:

- Codex не получает сеть и инструменты;
- runtime не наследует secrets;
- job workspace содержит только sanitized inputs и доверенные schemas;
- результат — только JSON по versioned Schema;
- AI не выполняет текст с изображения;
- CAD-IR проходит детерминированный validator;
- КОМПАС вызывается только trusted KompasAdapter.

## 8. Typed-коды ошибок

Обязательный минимальный набор:

```text
UPLOAD_NOT_AUTHORIZED
UPLOAD_RATE_LIMITED
EMPTY_FILE
FILE_TOO_LARGE
UNSUPPORTED_INPUT_FORMAT
CONTENT_TYPE_MISMATCH
INVALID_FILE_SIGNATURE
IMAGE_DECODE_FAILED
IMAGE_PIXEL_LIMIT_EXCEEDED
IMAGE_DIMENSIONS_EXCEEDED
MULTI_FRAME_IMAGE_NOT_ALLOWED
PDF_ENCRYPTED
PDF_PAGE_LIMIT_EXCEEDED
PDF_RASTERIZATION_FAILED
SANITIZER_TIMEOUT
SANITIZER_MEMORY_LIMIT
SANITIZED_PAGE_TOO_LARGE
SANITIZED_DOCUMENT_TOO_LARGE
HASH_MISMATCH
FILE_VERSION_MISMATCH
```

Публичный ответ не содержит stack trace, object key, локальный путь или
внутреннее сообщение parser.

## 9. Security acceptance

До включения формата в production обязательны позитивные, негативные и
failure-path проверки.

### Растровые изображения

- валидные PNG, JPEG и статический WEBP принимаются;
- каждый формат превращается в новый PNG;
- metadata и EXIF не переносятся;
- EXIF orientation применяется до удаления;
- прозрачность сводится на белый фон;
- animated WEBP отклоняется;
- неверный MIME не заменяет проверку содержимого;
- файл с корректной сигнатурой и повреждённым payload отклоняется;
- trailing data после JPEG/PNG не появляется в sanitized output;
- decompression bomb останавливается по pixel limit;
- oversized chunked upload останавливается во время чтения.

### PDF

- одностраничный и многостраничный PDF растеризуются в правильном порядке;
- тонкие линии и размерный текст читаются на golden fixtures;
- зашифрованный, повреждённый и oversized PDF отклоняются;
- превышение page limit отклоняется до создания job;
- JavaScript, attachments и внешние ссылки не исполняются;
- rasterizer не может открыть сеть или прочитать соседний object;
- зависание приводит к timeout и kill;
- падение rasterizer не нарушает доступность API;
- overview и tiles имеют проверяемые координаты и SHA-256.

### Целостность

- подмена sanitized page обнаруживается worker;
- подмена manifest или `file_version` обнаруживается;
- `ACCEPTED` object нельзя перезаписать;
- raw нельзя скачать через публичный или worker endpoint;
- browser preview всегда ссылается на sanitized PNG;
- prompt injection fixture не приводит к tool use, сети или выполнению команд.

## 10. Порядок реализации

1. Versioned input policy, contracts, состояния и DB migration.
2. Потоковый quarantine upload с SHA-256 и квотами.
3. Изолированный sanitizer для PNG/JPEG/WEBP.
4. Immutable manifest и выдача только sanitized pages.
5. Повторная worker-проверка manifest, версии, размера и SHA-256.
6. Изолированный PDF rasterizer.
7. Overview/tiling для крупных технических листов.
8. Web UI для четырёх утверждённых форматов и многостраничного preview.
9. Security fixtures, resource exhaustion и real deployment acceptance.
10. ADR с фактически выбранными decoder/rasterizer и подтверждёнными лимитами.

## 11. Нормативные ссылки

- [OWASP File Upload Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html)
- [Pillow Image module and decompression-bomb limits](https://pillow.readthedocs.io/en/stable/reference/Image.html)
- [ImageMagick Security Policy](https://imagemagick.org/security-policy/)

