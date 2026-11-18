# Продолжение с другого устройства

Репозиторий: https://github.com/zlw0x/kontur_ai, основная ветка `master`.
Приоритет: закончить этап 2, затем расширять фото; оплата следует после проверки
редактирования. План: `KONTUR-1.0-RELEASE-PLAN.md`. Решения: ADR-042.
Доказательства: `acceptance/KONTUR-EDIT-001-parametric-project-milestone.md`.

## Поднять исходники и проверки

Нужны Git, Python 3.12 и Node.js 24. Для стандартного production worker нужны
также .NET 8 SDK и Docker. Не копируйте токены и `.env` в Git.

```powershell
git clone https://github.com/zlw0x/kontur_ai.git
cd kontur_ai
git checkout master
git pull --ff-only
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r apps/api/requirements.txt -r apps/cad-worker/requirements.txt -r packages/image-sanitizer/requirements.txt
npm ci --prefix apps/web
$env:WORKER_REPOSITORY_MODE='memory'
.\.venv\Scripts\python.exe -m pytest -q
npm run typecheck --prefix apps/web
npm run build --prefix apps/web
```

Для работающего сервиса настройте PostgreSQL и существующий worker по README,
примените миграции, включая `0013_cad_projects`. Для автоматического прохождения
без инженерной модерации требуется явное `AUTOMATIC_ACCEPTANCE=true`.

## Что сохранено

Исходники, тесты, схемы, миграции и план лежат в Git. В
`examples/kontur-editing-milestone` сохранён переносимый пример: пять версий
CAD-IR, итоговые STEP/STL и проверка геометрии. Его можно использовать как
исходные данные при продолжении разработки.

Git не синхронизирует пользовательскую БД, учётные записи и новые загруженные
файлы. Локальная среда приёмки `.local/preview.sqlite` и `.local/preview-artifacts`
остаётся на исходном ПК; `.local` намеренно исключена из Git. Автоматического
импорта переносимого примера в личный кабинет пока нет.

Для одного личного кабинета на нескольких устройствах следующий отдельный шаг —
развернуть общий API, PostgreSQL и хранилище файлов с резервным копированием.
Текущий PR сохраняет разработку и контрольный пример, но не является таким
развёртыванием. Приватные данные, credentials, `.env`, `.venv` и `node_modules`
не должны попадать в репозиторий.
