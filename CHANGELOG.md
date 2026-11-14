# Changelog

## 2.0.0
- **Schema v2.0**: window rows now have 47 columns: 7 metadata + 11 legacy v1 features (unchanged) + 29 new features (`features_v2.py`). Column lists are defined once in `schema.py`.
- New window file `importantsimp_v2_<session>.csv`. An existing v1 file is renamed to `importantsimp_legacy_v1_<session>.csv` on first launch (never deleted). The raw log schema is unchanged.
- Boot-proof timestamps: per-launch `boot_id`, `anchors_<session>.csv` (every 60 s), and `boot_id` + `wall_start_utc` on window and survey rows. `align.py` maps raw `ts_ns` to UTC.
- Server validates `schema_version` and column count (400 on malformed rows). v2 rows go to `data_v2/`, v1 rows (including unsent queued ones, tagged `1.x`) go to `data_legacy/`, surveys go to `surveys_v2/`.
- New tray item: **Open Raw Data Folder**. Show Version also shows the data folder path.
- Raw log is flushed every 5 s and fsynced every 30 s and on shutdown. Write failures are retried and never crash the logger.
- Uninstall no longer deletes the raw typing logs (`%LOCALAPPDATA%\TypeSense\simple_data`); everything else is still removed.
- Privacy unchanged: no key content is recorded or sent, and the raw log never leaves the participant's PC.

## 1.3.1
- Previous release.
