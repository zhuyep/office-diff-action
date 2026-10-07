# Changelog

All notable changes to this project are documented here.

## [Unreleased]

### Added

- Standard-library-only `doctor` and `preflight` commands for Python 3.9+;
  neither requires Pillow, LibreOffice or Poppler.
- Bounded environment snapshots covering platform, discovered tool versions,
  fontconfig font families and observed font-file hashes; `doctor --output`
  refuses to overwrite an existing file.
- DOCX/PPTX extracted-text and font-declaration preflight, optional baseline
  environment comparison, offline HTML/JSON reports and `--fail-on-warning`.
- A one-command synthetic demo and saved offline examples for text changes and
  environment drift, explicitly marked as synthetic environment evidence.
- Environment snapshots in existing `compare`/`action` reports, including
  `environment.json`, a summary field, and HTML/Markdown fingerprint limitations.

### Changed

- Clarified that font declarations do not establish actual font usage, unresolved
  themes and palettes are not missing-font findings, and absent or partial font
  evidence is unknown.
- Documented fingerprint gaps and corrected the cross-build reproducibility
  claim: the Dockerfile does not lock renderer or font apt package versions.

Existing `compare`/`action` options and exit behavior are unchanged; font risks
do not affect the Action status. The package version and released Action image
are unchanged. This preflight MVP does not establish full local Office rendering
validation or deterministic rendering.

## [0.1.1] - 2026-09-02

### Changed

- Added a complete Simplified Chinese README and contribution guide.
- Added a bilingual project introduction for Chinese and international users.

## [0.1.0] - 2026-09-02

### Added

- DOCX and PPTX rendering through LibreOffice and Poppler.
- Per-page base/current/difference contact sheets.
- OOXML text extraction and unified text diffs.
- Markdown, HTML, and JSON reports.
- Git range discovery for GitHub Actions.
- Docker Action packaging and synthetic demo.

[Unreleased]: https://github.com/zhuyep/office-diff-action/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/zhuyep/office-diff-action/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/zhuyep/office-diff-action/releases/tag/v0.1.0
