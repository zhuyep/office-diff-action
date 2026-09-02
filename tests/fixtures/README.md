# Synthetic fixtures

These Office files contain no private or third-party content. They are generated
by `examples/make_demo.py` and are committed so the Docker Action can perform a
real LibreOffice rendering smoke test in CI.

Regenerate them with:

```bash
python -m pip install -e ".[demo]"
python examples/make_demo.py
cp examples/generated/{before,after}.{pptx,docx} tests/fixtures/
```
