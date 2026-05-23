# Prism MC Modpack Downloader

Скачивает **Minecraft** модпаки с **CurseForge** и упаковывает их в готовый инстанс **Prism Launcher**
со всеми модами, конфигами, ресурспаками и шейдерами — без необходимости качать
каждый мод отдельно через браузер.

`#minecraft` `#modpack` `#curseforge` `#prismlauncher` `#minecraft-mods` `#modpack-downloader` `#python` `#flask`

## Быстрый старт

```
start.bat
```

Скрипт сам создаст виртуальное окружение, папку download/, установит зависимости,
откроет браузер и запустит сервер.

**Перед первым использованием:** нажмите «Настройки API» в интерфейсе и
введите ваш CurseForge API ключ. Получить: https://console.curseforge.com

## Структура проекта

```
modpackdownloader/
  app.py             # Flask-бэкенд (API + логика скачивания)
  index.html         # Фронтенд (SPA, чистый JS без фреймворков)
  config.json        # CurseForge API ключ (пустой, нужно ввести свой)
  requirements.txt   # Python-зависимости
  start.bat          # Запуск одной кнопкой (создаёт venv, download/, ставит deps)
  .gitignore         # Исключает venv/, tmp/, download/ из репозитория
  README.md          # Этот файл

  venv/              # Виртуальное окружение (создаётся start.bat)
  tmp/               # Временные файлы (автоматически удаляются)
  download/          # Сюда сохраняются готовые ZIP-архивы (создаётся start.bat)
```

## Как это работает (архитектура)

```
Браузер ──HTTP──> Flask (port 5000) ──REST API──> CurseForge
                        │
                        ▼
              Скачивает структуру модпака (.zip)
              Читает manifest.json (список модов)
              Скачивает все моды (8 потоков)
              Собирает Prism-инстанс:
                .minecraft/mods/        <- моды
                .minecraft/config/      <- конфиги из overrides
                .minecraft/resourcepacks/
                .minecraft/shaderpacks/
                mmc-pack.json           <- Forge/Fabric версия
                instance.cfg            <- название инстанса
              Сохраняет в download/<name>.zip
```

### Ключевая особенность: стриминг без распаковки

Файлы конфигов НЕ распаковываются на диск — они копируются напрямую из
исходного CurseForge-ZIP в финальный ZIP через память с переименованием путей
(overrides/config/foo → .minecraft/config/foo). Это позволяет обрабатывать
модпаки со 100K+ файлов конфигов за секунды, а не минуты.

## API endpoints

### `GET /api/search?q=<запрос>&page=<N>`
Поиск модпаков на CurseForge. Возвращает список с id, названием, автором,
количеством загрузок, превью.

### `GET /api/modpack/<id>/files`
Список доступных версий модпака. Каждая версия имеет id файла, дату, размер,
версию игры и загрузчика.

### `POST /api/download`
Начинает скачивание. Тело запроса:
```json
{
  "modpack_id": 1459138,
  "file_id": 7999468,
  "display_name": "bloodfest-V-1.3.2"
}
```
Возвращает `download_id` для отслеживания прогресса.

### `GET /api/progress/<download_id>`
Статус скачивания. Поля ответа:
- `status` — "starting", "downloading", "done", "error"
- `progress` — число 0–100 (для прогресс-бара)
- `message` — текст текущей операции
- `done` / `total` — сколько модов скачано из скольки
- `current_file` — имя текущего файла
- `speed` — скорость скачивания (MB/s)
- `eta` — оставшееся время
- `downloaded_bytes` — всего скачано байт
- `filename` — имя готового файла (только при status="done")
- `size_mb` — размер готового файла (только при status="done")
- `failed` — сколько модов не удалось скачать (только при status="done")

### `GET /api/file/<download_id>`
Скачать готовый ZIP-архив инстанса.

### `GET/POST /api/config`
Получить или обновить API ключ CurseForge.

## Описание app.py (backend)

### Конфигурация

- `BASE_DIR` — папка с app.py
- `DOWNLOAD_DIR` — download/ (куда сохраняются готовые архивы)
- `API_BASE = "https://api.curseforge.com"` — CurseForge API
- `GAME_ID = 432` — Minecraft
- `MODPACK_CLASS_ID = 4471` — категория модпаков

### Основные функции

**`api_get(path, params)`** — GET-запрос к CurseForge API с авторизацией.
Таймаут 15 секунд. Вызывает `raise_for_status()` при ошибке.

**`cdn_url(file_id, filename)`** — генерирует URL для скачивания файла с CDN
CurseForge. Формат: `https://edge.forgecdn.net/files/{first_part}/{last_3}/{filename}`

**`classify_file(name)`** — определяет, в какую папку положить файл:
- `.jar` → `mods`
- `.zip` с ключевыми словами (shader, bsl, seus и т.д.) → `shaderpacks`
- остальные `.zip` → `resourcepacks`
- всё остальное → `mods`

**`download_file(url, dest, dl_id, filename, retries=3)`** — скачивает файл
с прогрессом. Обновляет `speed`, `eta`, `current_file`, `downloaded_bytes`
в словаре `downloads[dl_id]`. При ошибке retry 3 раза с паузой 1 сек.

**`do_download(dl_id, modpack_id, file_id, display_name)`** — основной процесс:
1. Получает информацию о файле модпака через API
2. Скачивает ZIP-архив структуры модпака (содержит manifest.json и overrides)
3. Читает manifest.json напрямую из ZIP (без извлечения)
4. Определяет Minecraft версию, загрузчик (Forge/NeoForge/Fabric/Quilt)
5. Скачивает все моды из манифеста в 8 потоков
6. Собирает ZIP-архив Prism-инстанса:
   - Стримит все файлы из структуры ZIP с переименованием путей
   - Добавляет скачанные моды (с авто-классификацией)
   - Добавляет mmc-pack.json и instance.cfg

### Формат прогресса

`downloads[dl_id]` — словарь, который опрашивается фронтендом:
```python
{
  "status": "downloading",     # starting / downloading / done / error
  "progress": 45,              # 0-100
  "message": "Загрузка 420 модов...",
  "done": 189,                 # сколько модов обработано
  "total": 420,                # всего модов
  "current_file": "mod.jar",   # текущий скачиваемый файл
  "speed": "5.2 MB/s",
  "eta": "1m 30s",
  "downloaded_bytes": 12345678
}
```

### Этапы прогресса

| % | Что происходит |
|---|----------------|
| 1 | Получение информации о модпаке |
| 2 | Скачивание структуры (manifest + overrides) |
| 25-90 | Загрузка модов (8 потоков) |
| 90-99 | Сборка финального ZIP (стриминг конфигов + моды + метаданные) |
| 100 | Готово |

## Описание index.html (frontend)

SPA на чистом JS без фреймворков. Состояние хранится в глобальном объекте `state`.

### Основные функции

**`showSettings()` / `saveSettings()` / `closeSettings()`** — модальное окно
для ввода API ключа CurseForge.

**`doSearch(page)`** — поиск модпаков. Отображает результаты в виде карточек
с логотипом, названием, автором, загрузками.

**`showDetail(id, name, ...)`** — открывает страницу модпака со списком версий.

**`renderFiles(files)`** — отображает таблицу версий с кнопкой "Скачать с модами".

**`startDownload(modpackId, fileId, name, btn)`** — начинает скачивание:
создаёт блок прогресса, отправляет POST на `/api/download`, запускает polling.

**`pollProgress(dlId)`** — опрашивает `/api/progress/<id>` каждые 500мс.
Обновляет прогресс-бар, проценты, скорость, ETA, имя текущего файла.
Таймаут: 15 минут (1800 итераций × 500мс).

**`renderDone(dlId, data)`** — отображает блок с результатом: сколько модов
скачано, размер файла, кнопка скачивания, инструкция по импорту в Prism.

### Вспомогательные функции

- `el(id)` — сокращение для `document.getElementById()`
- `esc(s)` — экранирование HTML (XSS защита)
- `fmtNum(n)` — форматирование чисел (1000 → 1.0K, 1000000 → 1.0M)

### Важные элементы UI

- `#pFill` — прогресс-бар (ширина в процентах)
- `#pPct` — числовое значение процентов
- `#pText` — основной текст статуса
- `#pMsg` — имя текущего файла или детальное сообщение
- `#pSpeed` — скорость скачивания
- `#pETA` — оставшееся время

## Возможные проблемы и решения

### "Bad CRC-32 for file ..."
Ошибка при стриминге файлов из структуры ZIP в финальный. Решение: создавать
новый `ZipInfo` через конструктор, а не мутировать существующий из исходного ZIP.

### "Ошибка: 403 Forbidden" при скачивании
API ключ CurseForge невалидный или истёк. Получить новый:
https://console.curseforge.com → API Keys

### "Ошибка: 429 Too Many Requests"
Слишком частые запросы к CurseForge API. Механизм retry в `download_file`
должен справиться, но может замедлить скачивание.

### "No module named flask"
Не установлены зависимости. Запуск `start.bat` установит их автоматически,
или вручную: `pip install -r requirements.txt`



### Ошибка импорта в Prism
Используйте "Добавить инстанс" → "Импортировать" → выберите ZIP-файл.
Можно также перетащить ZIP в окно Prism Launcher.

---

## Поддержать автора

Я создал этот софт, потому что сам задолбался вручную собирать модпаки для Prism.
Если хочешь отблагодарить — буду рад :)

[🇺🇦 Поддержать донатом (monobank)](https://send.monobank.ua/jar/2qiYgvFTRG)
