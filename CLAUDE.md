# Release checklist (for Claude Code)

Cutting a release for this repo involves more than tagging. Steps, in order:

1. **Bump the version in two places** — they are not linked:
   - `version.py` (`__version__`) — this is what ships inside the exe and is what `updater.py`'s `_is_newer()` compares against the release tag. If this isn't bumped to match the tag, every machine that updates will keep reporting the old version and re-trigger the "update" forever.
   - `TypeSenseLogger.iss` (`AppVersion=`) — cosmetic, shown in the installer / Add-or-Remove Programs. Not read by the updater logic, but should still match.

2. **Rebuild the app exe**: `dist/TypeSenseLogger/` must be cleared first (`build.bat` / PyInstaller refuses to write into a non-empty output dir), then run `build.bat`. This produces `dist/TypeSenseLogger/TypeSenseLogger.exe` and copies `config.json` into that folder.

3. **Build the actual release asset — this is the step that's easy to miss.**
   `updater.py` downloads a release asset named exactly `TypeSenseSetup.exe` (`_INSTALLER_ASSET_NAME`). That's produced from `TypeSenseLogger.iss` via the Inno Setup compiler (`ISCC.exe`), **not** by `build.bat`.
   - As of 2026-07-23, `installer.bat` (referenced in the README) does not exist in this repo and has never been committed (`git log --all -- installer.bat` is empty).
   - As of 2026-07-23, Inno Setup's compiler (`ISCC.exe`) is not installed in this dev environment, so this step cannot be done from here — it needs to run wherever Inno Setup actually is (or Inno Setup needs installing first).
   - A release without `TypeSenseSetup.exe` attached is silently useless for auto-update: `_check_once()` just logs "no asset attached" and does nothing. It won't error visibly.

4. **`config.json` carries secrets and is gitignored on purpose** — `server_url`, `secret_token`, and (as of the DND/updater-auth work) `github_token` all live there rather than hardcoded in tracked `.py` files, specifically so a real credential never lands in git history on this public repo. When adding new secret-like config, follow that pattern rather than a source constant.

5. **`gh release create` should be marked `--prerelease` unless the user explicitly says to make it the real "latest" release.** GitHub's `/releases/latest` API endpoint (which `updater.py` polls) excludes prereleases entirely — marking something prerelease is a safe way to stage a release without any installed client picking it up yet.

6. Version bumps have historically gone through their own PR (see PR #14, "Bump version to 1.2.0") rather than being bundled into a feature PR.
