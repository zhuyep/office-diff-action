# Contributing

Thanks for helping make Office changes reviewable.

## Before opening code

Please open an issue for a new feature. Rendering bugs can go straight to a pull
request when they include a minimal document that demonstrates the failure.

Never submit a confidential or customer-owned document. Recreate the problem in
a small synthetic file and remove author names, comments, revision history,
custom XML, embedded files, and external links.

## Development

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
```

An ideal commit contains the implementation, tests, documentation, and a small
reproduction when one is needed.

## Pull-request checklist

- [ ] The behavior is covered by a test.
- [ ] User-facing behavior is documented.
- [ ] Test documents are synthetic and safe to publish.
- [ ] No generated report contains local paths or confidential content.
- [ ] `python -m unittest discover -s tests -v` passes.
