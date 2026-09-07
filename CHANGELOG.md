# Changelog

Newest first. One line per user-visible change, prefixed `Added` / `Changed` /
`Fixed` / `Removed`. Settings › Updates renders this file, so write for the
person using the app, not for git log.

## Unreleased

- Added: first-launch sign-in gate; pixiv and X sessions from the site's own login page
- Added: live tag validation, preview strip and suggested tags in the character form
- Added: in-app updates with a daily check and a rail banner
- Added: Settings › Theme (background colour, plate opacity and blur, cut corners)
- Added: Shutdown button in the rail (desktop)
- Added: Settings › Language — interface language or follow the system, translation coverage, and number/date/time/file-size formats with a live preview
- Added: per-character source checkboxes (pixiv, X, or both) in the character form; the crawl skips whatever is unticked
- Changed: cyber build design — Chakra Petch, magenta ember, square plates by default
- Added: language setting (English; Japanese, Indonesian, Chinese and Filipino planned)
- Added: by-character folders are now written during download (hardlinks where the drive allows)
- Fixed: the crawl explains a missing pixiv sign-in once instead of failing per tag

## 0.1.0 — 2026-09-06

- Added: pixiv discovery by character tag with visited-set gating and dHash dedupe
- Added: X follow feed through gallery-dl, filtered by match terms
- Added: content-addressed library with per-character hardlink folders
- Added: DNS-over-HTTPS and proxy layers for blocked connections
