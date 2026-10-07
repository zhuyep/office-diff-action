# Security Policy

## Supported versions

Security fixes are applied to the latest release.

## Reporting a vulnerability

Please use GitHub private vulnerability reporting instead of a public issue.
Include the affected version, the smallest safe reproduction, and expected
impact. Do not attach private Office documents.

## Data boundary

Office Diff processes documents on the local machine or GitHub Actions runner.
It does not send documents to a hosted API. Workflow authors decide whether
generated reports are uploaded as Actions artifacts and who may access them.

Reports can contain extracted document text, document filenames, font declarations
and inventories, platform information, tool versions and font-file hashes. This
also applies to `summary.json` and environment snapshots. Review these contents
before sharing a report made from a sensitive document. The saved demo reports
use synthetic documents and clearly labeled synthetic environment data.

## Preflight and environment capture

`preflight` reads bounded DOCX/PPTX ZIP/XML content without opening it in an Office
renderer. It does not execute document macros or follow external document links.
It requires no renderer, Pillow, API key or network service. Supplied environment
snapshots are validated as bounded JSON data; they are not executed.

`doctor`, and `preflight` when no current snapshot is supplied, collect read-only
environment observations. They only query tool executables already discoverable
on `PATH`: LibreOffice, Poppler's `pdftoppm` and `pdfinfo`, and fontconfig's
`fc-list` for versions and the font inventory. Font files reported by fontconfig
are read within limits to calculate hashes. Capture does not install software,
change fonts, update fontconfig rules or modify Office settings. Existing visual
comparison commands also capture this environment evidence.

`doctor --output` creates a new file and refuses existing targets. Preflight
reports use the existing guarded report-directory handling. A warning or a
matching environment fingerprint is not a security assessment or a guarantee of
font selection, rendering equivalence or document safety.

## Rendering mode

Office documents can contain active or external content. The Action renders them
inside its container, does not execute macros, and does not support legacy binary
Office formats. Treat untrusted documents as untrusted input and use GitHub's
normal restrictions for workflows triggered by forks.
