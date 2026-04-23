# Planeta Kino Dashboard

Нативний десктоп-дашборд + парсер фільмів з planetakino.ua. MVP для одного кінотеатру — **Одеса (City Center Котовський)**, архітектура тримає інші 13 кінотеатрів.

- **macOS:** `PlanetaKino.app` / `PlanetaKino-0.2.0.dmg` (~25 MB)
- **Windows:** `PlanetaKino.exe` у портативному ZIP (~30 MB)
- **Linux / DevMode:** `python3 app.py`

## Що це робить

1. **Тягне дані з двох розділів сайту:**
   - `/schedule/?cinema=cinema-9-uk` — «Вже в кіно» (поточний розклад сеансів).
   - `/coming-soon/?cinema=cinema-9-uk` — «Скоро в кіно» (майбутні прем'єри).
2. **Збагачує** кожен фільм з його детальної сторінки через JSON-LD Movie schema:
   оригінальна назва, тривалість (ISO-8601), дата прем'єри, жанри, опис, постер, трейлер.
3. **Зберігає в SQLite** з історією snapshot-ів (ловить зсуви дати, зміну постера, перенесення прем'єри).
4. **Показує нативний дашборд** — PyWebView-вікно з фільтрами, пошуком, сортуванням, DCP-колонкою, автооновленням і експортом.
5. **Інтегрується з `dcp_ftp_reader`** (опційно): зчитує SQLite DCP-читача у read-only mode і додає колонку статусу DCP / KDM до кожної картки.

## Швидкий старт (dev)

```bash
# Залежності (одноразово)
pip3 install -r requirements.txt

# Запустити нативний додаток
python3 app.py

# Або окремо CLI-парсер
python3 -m planetakino fetch --export
python3 -m planetakino export
```

## Збірка

### macOS — `.app` + `.dmg`

```bash
bash build/build_mac.sh
# → dist/PlanetaKino.app
# → dist/PlanetaKino-0.2.0.dmg
```

### Windows — `.exe` (через GitHub Actions)

```bash
git tag v0.2.0 && git push --tags
# GitHub Actions зробить build-windows і прикріпить .zip до релізу.
```

Локально на Windows:

```powershell
powershell -ExecutionPolicy Bypass -File build\build_windows.ps1
```

### Генерація іконки

```bash
python3 build/make_icon.py
# → build/icon/icon.icns (macOS)
# → build/icon/icon.ico  (Windows)
# → build/icon/icon.png  (1024×1024)
```

## Структура

```
planetakino/
├── config.py          Кінотеатри, URL, таймаути, дефолтні налаштування
├── http.py            Клієнт із ретраями, UA, бекофом
├── settings.py        Persistent user settings (data/settings.json)
├── api.py             Python↔JS bridge (PyWebView js_api)
├── dcp_bridge.py      Integration з dcp_ftp_reader (read-only SQLite join)
├── parser/
│   ├── listing.py     parse_listing + parse_schedule
│   └── detail.py      JSON-LD Movie schema → структуровані дані
├── extractors/
│   ├── date_uk.py     "30 квітня" → date + визначення року
│   └── duration.py    "1 год 48 хв" / "PT1H44M" → minutes
├── db/store.py        SQLite WAL, movies + snapshots + fetch_log
├── pipeline.py        Склейка: fetch → enrich → upsert → export
└── __main__.py        CLI

app.py                 PyWebView entry point (wraps web/index.html)
web/index.html         SPA dashboard (Tailwind CDN, vanilla JS)

build/
├── make_icon.py       Pillow → icon.icns/ico/png
├── planetakino.spec   PyInstaller spec (cross-platform)
├── build_mac.sh       .app + .dmg
├── build_windows.ps1  .exe + .zip
└── icon/              Generated icons

data/
├── planetakino.db     SQLite (WAL)
├── movies.json        JSON export для фронта
├── settings.json      User settings
├── reports/           Markdown звіти (кнопка ЗВІТ)
├── exports/           JSON/CSV/MD експорти
└── app.log            Лог нативного додатку

.github/workflows/
├── build.yml          Cross-platform build .app + .dmg + .exe
└── tests.yml          pytest на кожен push

tests/
├── fixtures/          HTML-снапшоти для регрес-тестів
└── test_*.py          27 тестів
```

## Bridge API (Python ↔ JavaScript)

Методи доступні з фронтенду через `window.pywebview.api`:

| Метод                               | Призначення |
|------------------------------------|-------------|
| `app_info()`                       | Версія, дата білду, uptime, шлях до БД/логу |
| `list_movies(cinema_key?)`         | Фільми + DCP статус, налаштування, мета |
| `refresh(force_detail?)`           | Кнопка **ОНОВИТИ** — повний fetch + export |
| `refresh_week()`                   | **ОНОВИТИ ТИЖДЕНЬ** — ігнорує detail-кеш |
| `refresh_movie(movie_id)`          | Кнопка ↻ на картці |
| `delete_movie(movie_id)`           | Кнопка × на картці |
| `movie_snapshots(movie_id)`        | Історія змін (для модалки) |
| `fetch_log(limit?)`                | Останні fetch-цикли |
| `get_settings()` / `update_settings(changes)` | Persistent settings |
| `list_cinemas()`                   | Для селектора кінотеатрів |
| `open_external(url)`               | Відкриває URL у системному браузері |
| `open_in_editor(path)` / `reveal_in_finder(path)` | **SUBLIME** / Reveal |
| `export(fmt, cinema_key?)`         | `json` / `csv` / `md` |
| `generate_report()`                | **ЗВІТ** — Markdown-звіт в `data/reports/` |
| `start_auto_refresh()` / `stop_auto_refresh()` | Фонова петля |
| `dcp_probe(path)` / `dcp_status()` | Валідація DCP-читача та зведення |

## Тести

```bash
python3 -m pytest tests/ -q
```

Покриття:
- `extractors/` — дати, тривалість, крайові випадки (20 тестів).
- `parser/` — листинг + детальна сторінка проти живих HTML-фікстур (7 тестів).

## Дизайн-рішення

- **Native via PyWebView, не Electron:** WebKit на Mac + WebView2 на Windows. ~25 MB замість 150 MB, без Node.js у застосунку. Python може не ставитися — PyInstaller бандлить інтерпретатор.
- **Listing → Detail дворівнево:** листинг дає тільки `id`/`slug`/назву UA/постер. Решта — з детальної сторінки через JSON-LD. ~37 HTTP/цикл.
- **Чому не Nuxt state:** IIFE з 109-змінною таблицею дедупу, ламається при зміні версії Nuxt. JSON-LD — SSR-стабільний контракт.
- **DCP як read-only приєднання:** ми не пишемо в `dcp_servers.db`, тільки читаємо по normalized title. Якщо читач не налаштований — колонка просто показує "н/д".
- **Визначення допрем'єри:** назва містить «ДОПРЕМ'ЄРНИЙ». SSR HTML не має окремого лейбла (рендериться з Nuxt state).
- **Рік у датах:** якщо «30 квітня» дає дату в минулому > 30 днів — перекочуємо на наступний рік. Не хардкодимо.
- **Кеш детальних сторінок:** 7 днів за замовчуванням (налаштовується). Кнопка **ОНОВИТИ ТИЖДЕНЬ** форс-refresh-ить усі деталі.
- **Snapshots:** будь-яка зміна `title_uk` / `premiere_date` / `duration` / `poster` / `section` → рядок у `snapshots`. Історія видно в модалці фільму.
- **Два різних селектори для двох розділів:** `a[data-component-name="BaseMovieCardItem"]` (coming-soon), `div[data-component-name="MovieWithSessionsCard"]` (schedule).
- **Settings persisted у `data/settings.json`** — атомарний запис через `.tmp` + rename.

## DCP інтеграція

Увімкніть у **Налаштуваннях → DCP → Enable** і вкажіть шлях до директорії `dcp_ftp_reader` (або напряму до `dcp_servers.db`). Статуси:

| Status            | Що означає |
|-------------------|------------|
| `no_keys_needed`  | KDM не потрібен — фільм програється без ключа |
| `pending`         | Файл ще не прийшов на FTP |
| `waiting_key`     | DCP прибув, ключ не отриманий — тикає таймер «3д 12г» |
| `key_ready`       | DCP + ключ є, ще не скачано локально |
| `ready`           | Повна готовність |

Матчинг — по normalized title (casefold + стрип розділових знаків + прибирання префіксу «ДОПРЕМ'ЄРНИЙ» та формат-маркерів типу IMAX/3D).

## Cron (опціонально, окремо від GUI)

```
0 6 * * * cd /Users/r/Desktop/planetakino && /usr/bin/python3 -m planetakino fetch --export >> /tmp/planetakino.log 2>&1
```

GUI-ва автооновлююча петля тікає всередині `app.py` і керується з налаштувань (інтервал у хвилинах, 0 = off).

## Журнал

- **2026-04-23 MVP v0.1** — 27 тестів, 37 фільмів парсяться, HTML-дашборд.
- **2026-04-23 v0.2 Native app** — PyWebView wrapper, Python↔JS bridge (22 методи), DCP інтеграція, іконка, PyInstaller spec, cross-platform CI, `.dmg` + `.exe`.
