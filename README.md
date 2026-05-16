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

## Фаза 3 (текущая)

- White-label: бренд, клиент, цвет, логотип, footer
- Экспорт PDF через Playwright (A4)

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

- `reports/*.html`, `reports/*.pdf` — сгенерированные отчёты после каждого запуска CLI; это результат работы инструмента на вашей машине, а не исходный код. В git остаётся только `reports/.gitkeep`, чтобы папка существовала в проекте.
- `data/*.sqlite` — локальная история проверок
- `__pycache__/`, `*.pyc` — кэш Python
- `.venv/`, `venv/`, `.env` — виртуальное окружение и секреты

После сканирования отчёты лежат локально в `reports/`; при необходимости их можно архивировать или отправить клиенту отдельно от git.

## Структура проекта

```
weekly-site-report/
  app/           # код CLI (storage, diff, branding, pdf)
  branding/      # пример JSON брендинга
  assets/        # логотипы и статика
  data/          # SQLite по умолчанию (не коммитится)
  templates/     # Jinja2-шаблон отчёта
  reports/       # локальные HTML/PDF (не коммитятся)
  tests/         # unit-тесты
  requirements.txt
  README.md
```
