# Project Context — Modpack Translator

## What this is
A Flask web app (Prism MC Modpack Downloader) that:
1. Downloads modpacks from CurseForge
2. Translates English lang files in downloaded ZIPs → Russian (`*_ru.zip`)
3. Handles `.jar` files inside modpack ZIPs (extracts, translates, repacks)

## Running
- `start.bat` opens `http://localhost:5000`
- Flask backend in `app.py`, frontend in `index.html`
- Python venv at `venv/`

## Translation backend
- Direct HTTP to `translate.googleapis.com/translate_a/t` with multiple `q=` params (batch 100, timeout 15s)
- No `deep_translator` / LibreTranslate
- Phase 1: collect all unique texts from ALL en_us.json/en_gb.json/en_us.lang/en_gb.lang (both root and inside .jar)
- Phase 2: filter junk (<3 chars, numbers/symbols, already cyrillic, color codes), translate unique strings via cache
- Phase 3: write output archive
  - Mods WITHOUT built-in ru_RU: create fresh ru_ru.json from cache
  - Mods WITH built-in ru_RU: MERGE — keep author's keys, add missing from Google
  - Mods without en_us: pass through as-is

## SNBT Quest Translation
- FTB Quests `.snbt` files in the ZIP are now also translated (titles, subtitles, descriptions)
- `translate_snbt.py` handles SNBT parsing with regex (not full NBT parser)
- Translation goes through the same Google Translate pipeline as lang files
- Only files containing `ftbquests` in path with `.snbt` extension are processed

## Key endpoints
- `POST /api/translate/upload` — upload ZIP, starts translation, deletes old `_ru.zip`
- `GET /api/translate/progress/<tl_id>` — poll progress
- `GET /api/translate/file/<tl_id>` — download result
- Upload saves as `upload_{safe}.zip`, result as `upload_{safe}_ru.zip`

## UI note
- Inline `onclick` with single quotes is broken; all UI uses `data-*` + `addEventListener`
- Background image: `static/background.jpg` (1920x1080, Minecraft theme)
- Color scheme: dark `#51301D`, light `#965E39`, bg overlay `#615350`

## User
- Russian speaker
- Wants to play modpacks in Russian
- Has Prism Launcher
- LibreTranslate NOT running (only for WoW Chinese client, not relevant here)
- Current test modpack: Sparkles_of_Purple_0_21.zip (257 MB, 117 mods, 20k+ strings)
