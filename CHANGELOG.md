# Changelog

## [1.1.0] — 2026-05-23

### Fixed
- Исправлен баг: карточки модпаков с апострофом (`'`) в названии не открывались.
  Замена инлайн `onclick` на `data-*` атрибуты + `addEventListener` через замыкание,
  что устранило XSS-подобную проблему с экранированием в HTML-атрибутах
  (`index.html: renderSearch`, `renderFiles`).

### Security
- `config.json` добавлен в `.gitignore`, чтобы API ключ не попадал в репозиторий.

## [1.0.0] — Initial release
