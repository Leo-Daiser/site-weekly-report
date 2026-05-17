# Weekly Site Report

Локальный CLI-инструмент для SEO-фрилансеров и веб-студий. Сканирует главную страницу сайта, проверяет базовые технические и SEO-параметры, часть внутренних ссылок и генерирует HTML-отчёт.

## Установка

```bash
pip install -r requirements.txt
```

Требуется Python 3.11+.

## Запуск

Из корня проекта:

```bash
python -m app.main --url https://example.com
```

### Параметры

| Параметр       | По умолчанию | Описание                              |
|----------------|--------------|---------------------------------------|
| `--url`        | —            | URL сайта (обязательный)              |
| `--max-links`  | 30           | Сколько внутренних ссылок проверить   |
| `--timeout`    | 10           | Таймаут HTTP-запросов (сек)           |
| `--output-dir` | `reports`    | Папка для сохранения HTML-отчёта      |
| `--db-path`    | `data/checks.sqlite` | SQLite-база истории проверок |
| `--brand-name` | —            | Название бренда в отчёте              |
| `--client-name`| —            | Имя клиента (white-label)             |
| `--brand-color`| `#2563eb`    | Акцентный цвет (#RRGGBB)              |
| `--brand-logo` | —            | Путь к логотипу (png/jpg/svg)         |
| `--footer-text`| —            | Текст в подвале отчёта                |
| `--branding-file` | —         | JSON с настройками брендинга          |
| `--format`     | `html`       | `html`, `pdf` или `both`              |

Пример с параметрами:

```bash
python -m app.main --url https://example.com --max-links 20 --timeout 15 --output-dir reports
```

Отчёт сохраняется как `reports/example_com_2026-05-16_14-30-00.html`.

## White-label reports

Отчёт можно оформить под своё агентство: название бренда, клиент, цвет, логотип и текст в подвале. Настройки задаются через CLI или JSON-файл (`--branding-file`). CLI-параметры имеют приоритет над файлом.

Пример:

```bash
python -m app.main --url https://example.com \
  --brand-name "SEO Studio" \
  --client-name "Client Company" \
  --brand-color "#2563eb" \
  --format html
```

### Branding JSON

Пример `branding/default.json`:

```json
{
  "brand_name": "WebReport Weekly",
  "client_name": null,
  "brand_color": "#2563eb",
  "logo_path": null,
  "footer_text": "Prepared by WebReport Weekly",
  "show_powered_by": true
}
```

Запуск с файлом:

```bash
python -m app.main --url https://example.com --branding-file branding/default.json --format both
```

Логотип встраивается в HTML как base64 (self-contained). Если файл логотипа не найден, выводится предупреждение, отчёт создаётся без логотипа.

## PDF export

Для PDF нужен Playwright и Chromium:

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

Пример HTML + PDF:

```bash
python -m app.main --url https://example.com \
  --brand-name "SEO Studio" \
  --client-name "Client Company" \
  --format both
```

Файлы сохраняются рядом: `reports/example_com_YYYY-MM-DD_HH-MM-SS.html` и `.pdf`.

- `--format html` — только HTML (по умолчанию)
- `--format pdf` — HTML (для рендера) + PDF; при ошибке PDF процесс завершается с ошибкой
- `--format both` — оба файла; при ошибке PDF HTML всё равно сохраняется

## История проверок

Каждый запуск сохраняет снимок проверки в локальную SQLite-базу (по умолчанию `data/checks.sqlite`). Перед сохранением текущей записи программа ищет последнюю проверку того же домена и строит diff.

**Нормализация домена:** `https://www.example.com/page` → `example.com`; `https://sub.example.com` → `sub.example.com` (префикс `www.` убирается, поддомены сохраняются).

Запуск с базой по умолчанию:

```bash
python -m app.main --url https://example.com
```

Свой путь к базе:

```bash
python -m app.main --url https://example.com --db-path data/my_checks.sqlite
```

В HTML-отчёте блок **«Что изменилось с прошлой проверки»** показывает:

- сообщение о первой проверке, если истории ещё нет;
- список изменений с severity (`positive`, `neutral`, `warning`, `critical`);
- текст об отсутствии существенных изменений, если метрики совпали.

База и отчёты остаются на вашей машине (см. `.gitignore`: `data/*.sqlite` не коммитятся).

## Что проверяет первая версия (MVP)

- Доступность главной страницы (статус, редиректы, время ответа)
- SEO: title, meta description, H1, canonical, lang
- Наличие `robots.txt` и `sitemap.xml`
- Формы на странице (method, action, inputs, submit)
- Внутренние и внешние ссылки; проверка первых N внутренних на HTTP-ошибки
- HTML-отчёт с предупреждениями и рекомендациями

## Фаза 2

- SQLite-история проверок по домену
- Сравнение с предыдущей проверкой и блок изменений в отчёте

## Фаза 3

- White-label: бренд, клиент, цвет, логотип, footer
- Экспорт PDF через Playwright (A4)

## Batch reports

Пакетная генерация отчётов по списку клиентов из CSV:

```bash
python -m app.batch --clients data/clients.example.csv --output-dir reports --format html
```

С HTML и PDF:

```bash
python -m app.batch --clients data/clients.example.csv --output-dir reports --format both
```

### Формат CSV

Обязательные поля: `client_name`, `url`.

Опциональные: `client_email`, `brand_name`, `brand_color`, `brand_logo`, `footer_text`, `format`, `max_links`, `timeout`.

Если `format`, `max_links` или `timeout` пустые — используются значения из CLI (`--format`, `--max-links`, `--timeout`).

Пример: `data/clients.example.csv`.

### Результаты batch

Для каждого запуска создаётся папка:

`reports/batch_YYYY-MM-DD_HH-MM-SS/`

Внутри:

- HTML/PDF-отчёты по каждому сайту из CSV;
- `summary.csv` — сводная таблица по всем строкам;
- `summary.html` — та же сводка в виде HTML с относительными ссылками на отчёты.

При `--continue-on-error` (по умолчанию включён) ошибка одного сайта не останавливает обработку остальных; ошибка попадает в summary.

Подходит для первых клиентов агентства: подготовьте CSV, запустите batch, отправьте клиентам отчёты из batch-папки.

## Фаза 4

- Batch-режим по CSV (`python -m app.batch`)
- Общий pipeline для `app.main` и `app.batch`

## Email delivery and outbox

После batch можно подготовить письма клиентам. **По умолчанию письма не отправляются** (`--dry-run` включён): они сохраняются в `outbox/` для проверки. Реальная отправка — отдельное явное действие с `--no-dry-run`.

Инструмент предназначен для отправки отчётов **своим клиентам**, а не для массового спама.

### Workflow

```bash
python -m app.batch --clients data/clients.example.csv --output-dir reports --format both

python -m app.send_reports --batch-dir reports/batch_YYYY-MM-DD_HH-MM-SS --clients data/clients.example.csv --dry-run

python -m app.send_reports --batch-dir reports/batch_YYYY-MM-DD_HH-MM-SS --clients data/clients.example.csv --no-dry-run
```

Опционально сразу после batch:

```bash
python -m app.batch --clients data/clients.example.csv --output-dir reports --format both --create-outbox
```

### Outbox

Для batch-папки создаётся `outbox/<имя_batch>/`:

- `emails/*.txt` и `emails/*.html` — черновики писем;
- `manifest.csv` — список писем, статусы (`prepared`, `sent`, `failed`, `skipped`).

Просмотрите письма в outbox перед отправкой.

### SMTP

Скопируйте `.env.example` в `.env` или передайте параметры CLI (`--smtp-host`, `--smtp-username`, …).

При `--no-dry-run` без полного SMTP-конфига (см. `.env.example`) программа завершится с понятной ошибкой.

### CSV

Добавлено поле `client_email` (обязательно только для email-delivery). Для обычного batch без отправки email можно оставить пустым.

## Фаза 5

- Outbox с черновиками писем
- Отправка через SMTP (`python -m app.send_reports`)

## Weekly runner (Фаза 6)

`app.weekly` — единая точка входа для еженедельного процесса: batch-отчёты, outbox и (опционально) отправка писем. Это **не** daemon и **не** планировщик: расписание настраиваете вы сами (Windows Task Scheduler, cron и т.д.).

### Job-файл

Пример: `data/weekly_jobs.example.json`

| Поле | Описание |
|------|----------|
| `job_name` | Имя задачи для run-log |
| `clients_csv` | CSV клиентов (как в batch) |
| `output_dir` | Папка отчётов (`reports`) |
| `outbox_dir` | Папка outbox |
| `db_path` | SQLite истории |
| `branding_file` | JSON брендинга |
| `format` | `html`, `pdf`, `both` |
| `max_links`, `timeout` | Параметры сканирования |
| `create_outbox` | Задумано для автоматизации; в weekly outbox создаётся в режимах `outbox` и `send` |
| `send_email` | По умолчанию `false`; **игнорируется**, пока не указан `--mode send` |
| `continue_on_error` | Как в batch |
| `limit` | Ограничить число строк CSV (для тестов) |

### Режимы (`--mode`)

| Режим | Действие |
|-------|----------|
| `dry-run` (по умолчанию) | Проверить job, CSV и пути; вывести план; **ничего не генерировать и не отправлять** |
| `generate` | Только batch → `reports/batch_.../` + summary |
| `outbox` | Batch + outbox; email **не** отправляется |
| `send` | Batch + outbox + SMTP; нужен полный SMTP-конфиг |

По умолчанию `mode=dry-run`, чтобы случайно не отправить письма. Даже при `send_email: true` в JSON письма уйдут **только** с `--mode send`.

### Run log

Каждый запуск пишет JSON в `run_logs/weekly_run_YYYY-MM-DD_HH-MM-SS.json` (пути batch, outbox, счётчики, ошибка при сбое). Папка `run_logs/*` в `.gitignore`, в git остаётся только `run_logs/.gitkeep`.

### Примеры

```bash
python -m app.weekly --job-file data/weekly_jobs.example.json

python -m app.weekly --job-file data/weekly_jobs.example.json --mode dry-run

python -m app.weekly --job-file data/weekly_jobs.example.json --mode generate

python -m app.weekly --job-file data/weekly_jobs.example.json --mode outbox

python -m app.weekly --job-file data/weekly_jobs.example.json --mode send
```

С лимитом для теста:

```bash
python -m app.weekly --job-file data/weekly_jobs.example.json --mode generate --limit 2
```

### Планировщик (вручную)

**Windows Task Scheduler** — действие «Запуск программы»:

```text
python -m app.weekly --job-file data/weekly_jobs.example.json --mode outbox
```

Рабочая папка: корень проекта. Полный путь к `python` при необходимости.

**cron (Linux/macOS)** — пример по понедельникам в 09:00:

```cron
0 9 * * MON cd /path/to/weekly-site-report && python -m app.weekly --job-file data/weekly_jobs.example.json --mode outbox
```

Для реальной отправки замените `outbox` на `send` и настройте SMTP (`.env` или флаги `--smtp-*`).

## Следующие фазы (план)

- Планировщик еженедельных отчётов
- Мульти-страничный краул
- Web-интерфейс и учётные записи (SaaS)
- Интеграции (Search Console, аналитика)

## Тесты

```bash
python -m unittest discover -s tests -v
```

## Что не нужно коммитить

В репозиторий не попадают локальные артефакты и окружение (см. `.gitignore`):

- `reports/*` (кроме `reports/.gitkeep`) — HTML/PDF-отчёты и batch-папки `reports/batch_*` после запуска CLI
- `data/*.sqlite` — локальная история проверок
- `outbox/*` (кроме `outbox/.gitkeep`) — подготовленные письма
- `run_logs/*` (кроме `run_logs/.gitkeep`) — JSON-логи weekly-запусков
- `__pycache__/`, `*.pyc` — кэш Python
- `.venv/`, `venv/`, `.env` — виртуальное окружение и секреты

После сканирования отчёты лежат локально в `reports/`; при необходимости их можно архивировать или отправить клиенту отдельно от git.

## Структура проекта

```
weekly-site-report/
  app/           # main, batch, weekly, send_reports, pipeline, outbox, email_sender
  run_logs/      # JSON-логи weekly (не коммитится)
  outbox/        # черновики писем (не коммитится)
  data/          # clients.example.csv, SQLite (не коммитится)
  branding/      # пример JSON брендинга
  assets/        # логотипы и статика
  data/          # SQLite по умолчанию (не коммитится)
  templates/     # Jinja2-шаблон отчёта
  reports/       # локальные HTML/PDF (не коммитятся)
  tests/         # unit-тесты
  requirements.txt
  README.md
```
