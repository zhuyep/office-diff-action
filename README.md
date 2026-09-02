# Office Diff Action

**See what changed in Word and PowerPoint before you merge.**

[![Test](https://github.com/zhuyep/office-diff-action/actions/workflows/test.yml/badge.svg)](https://github.com/zhuyep/office-diff-action/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

GitHub can store `.docx` and `.pptx` files, but its normal diff cannot show a
reviewer that text reflowed, a slide moved, or a document stopped rendering.
Office Diff turns every changed page or slide into a base/current/difference
contact sheet and produces text and machine-readable diffs alongside it.

![Office Diff demo](assets/demo/page-001.png)

## What it produces

- a static HTML report you can open without a server;
- before/current/difference images for every page or slide;
- a unified diff of text extracted directly from Office Open XML;
- a JSON summary for later policy checks;
- a compact GitHub Actions job summary.

It supports `.docx` and `.pptx`. The project reviews documents; it does not edit
or generate them.

## Use it in a pull request

```yaml
name: Review Office changes

on:
  pull_request:
    paths:
      - "**/*.docx"
      - "**/*.pptx"

permissions:
  contents: read

jobs:
  office-diff:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Render Office diff
        id: office-diff
        uses: zhuyep/office-diff-action@v1
        with:
          base-ref: ${{ github.event.pull_request.base.sha }}
          head-ref: ${{ github.event.pull_request.head.sha }}

      - name: Upload visual report
        uses: actions/upload-artifact@v4
        with:
          name: office-diff-report
          path: office-diff-report
```

Open the `office-diff-report` artifact from the workflow run and then open
`index.html`.

## Use it locally

LibreOffice and Poppler must be available on `PATH`.

```bash
python -m pip install .
office-diff compare before.pptx after.pptx --output office-diff-report
```

The command exits non-zero when rendering fails. Text extraction still runs, so
the report records partial evidence instead of hiding the failure.

## Report structure

```text
office-diff-report/
├── index.html          # visual review
├── report.md           # portable Markdown report
├── summary.json        # automation-friendly result
└── documents/
    └── .../
        ├── base/       # rendered baseline pages
        ├── current/    # rendered proposed pages
        └── diff/       # three-panel review images
```

## Design choices

- **Rendering is evidence, not ground truth.** The Action pins LibreOffice,
  Poppler, and fonts to the same released container for both sides of a
  comparison. A future container release can still change rendering, and
  Microsoft Office can paginate a complex document differently.
- **No document leaves the runner.** The Action does not upload inputs to a
  third-party service. Uploading the generated artifact is an explicit workflow
  step controlled by the repository.
- **Changes do not fail by default.** An Office file is expected to change in a
  pull request. Rendering failures fail the Action; change-policy gates can read
  `summary.json`.
- **Review comes before scoring.** The first job is to show reviewers reliable
  evidence, not invent an opaque AI quality score.

## Inputs

| Input | Default | Purpose |
|---|---|---|
| `base-ref` | required | Baseline commit/ref |
| `head-ref` | `HEAD` | Proposed commit/ref |
| `output-dir` | `office-diff-report` | Report directory |
| `dpi` | `110` | Render resolution |
| `pixel-threshold` | `16` | Ignore small per-pixel differences |
| `allow-render-errors` | `false` | Keep the workflow green after render errors |

## Current limits

- The visual report is a workflow artifact, not an inline PR image gallery.
- Password-protected and legacy `.doc`/`.ppt` files are not supported.
- Git LFS-backed Office files currently stop with an explicit unsupported error.
- Fonts unavailable in the container are substituted.
- Pages/slides are matched by position; move detection is not yet semantic.
- LibreOffice rendering is close to, but not identical to, desktop Microsoft Office.
- One run accepts at most 20 changed documents and 200 pages/slides per document;
  render DPI is constrained to 36–300 to keep untrusted pull requests bounded.

These limits are deliberate and visible. Please open an issue with a small,
shareable sample document when you encounter a rendering problem.

## Roadmap

- optional PR comment linking to the workflow report;
- configurable checks for page-count and slide-count changes;
- font-substitution inventory;
- semantic slide matching for moved slides;
- XLSX support only if real users request it.

## Contributing

Small reproduction files and focused rendering cases are especially valuable.
See [CONTRIBUTING.md](CONTRIBUTING.md). By participating, you agree to follow
the [Code of Conduct](CODE_OF_CONDUCT.md).

## License

[MIT](LICENSE)
