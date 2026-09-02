# Security Policy

## Supported versions

Security fixes are applied to the latest release.

## Reporting a vulnerability

Please use GitHub private vulnerability reporting instead of a public issue.
Include the affected version, the smallest safe reproduction, and expected
impact. Do not attach private Office documents.

## Data boundary

Office Diff processes documents locally on the GitHub Actions runner. It does
not send documents to a hosted API. Workflow authors decide whether generated
reports are uploaded as Actions artifacts and who may access those artifacts.

Office documents can contain active or external content. The Action renders them
inside its container, does not execute macros, and does not support legacy binary
Office formats. Treat untrusted documents as untrusted input and use GitHub's
normal restrictions for workflows triggered by forks.
