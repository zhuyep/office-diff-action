"""Explain source and environment evidence without rendering Office documents."""

import difflib
import hashlib
import html
import json
import unicodedata
from pathlib import Path
from typing import Any, Dict, Optional

from . import ooxml
from .environment import compare_environments
from .font_declarations import inspect_fonts
from .ooxml import extract_text

LIMITATIONS = [
    "No pages were rendered. These checks do not attribute any pixel difference to a font.",
    "Font declarations can come from unused styles. Theme references are not resolved.",
    "A listed family does not prove glyph coverage, shaping, font selection or embedded-font use.",
    "Equal observed environment fingerprints do not guarantee equal rendering: fontconfig rules, "
    "Office settings, locale and other dependencies are not fully captured.",
    "Extracted text is not document equivalence. Formatting, images, charts and some fields are "
    "outside this check; PPTX text follows part filename order, not presentation order.",
]


def _families(inspection: Dict[str, Any]) -> set:
    return {entry["family"] for entry in inspection["declarations"] if entry["kind"] == "explicit"}


def _font_key(name: str) -> str:
    return unicodedata.normalize("NFC", " ".join(name.split())).casefold()


def _document(path: Path, environment: Dict[str, Any]) -> Dict[str, Any]:
    inspection = inspect_fonts(path)
    inventory = environment["fonts"]
    known = inventory["status"] == "available"
    installed = {_font_key(name) for name in inventory["families"]}
    families = sorted(_families(inspection), key=str.casefold)
    missing = [name for name in families if _font_key(name) not in installed] if known else []
    return {
        "name": path.name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "font_inspection": inspection,
        "declared_families": families,
        "inventory_check": "checked" if known else "unknown",
        "families_absent_from_inventory": missing,
    }


def build_preflight(
    base: Path,
    current: Path,
    environment: Dict[str, Any],
    baseline_environment: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if base.suffix.lower() != current.suffix.lower():
        raise ValueError("The two document versions must have the same format")
    # Inspect first: its strict package checks protect the legacy text extractor.
    base_result = _document(base, baseline_environment or environment)
    current_result = _document(current, environment)
    base_text, current_text = extract_text(base), extract_text(current)
    text_truncated = any(
        len(value) > ooxml.MAX_EXTRACTED_CHARACTERS for value in (base_text, current_text)
    )
    text_diff = "\n".join(
        difflib.unified_diff(
            base_text.splitlines(),
            current_text.splitlines(),
            fromfile="base/" + base.name,
            tofile="current/" + current.name,
            lineterm="",
        )
    )
    base_fonts, current_fonts = (
        _families(base_result["font_inspection"]),
        _families(current_result["font_inspection"]),
    )
    comparison = compare_environments(baseline_environment, environment)
    warnings = []
    if text_truncated:
        warnings.append(
            "Text extraction reached its character limit and was truncated. "
            "Changes beyond the extracted prefix are unknown."
        )
    if comparison["status"] == "changed":
        warnings.append(
            "Observed environment drift: compare renders in the same environment "
            "before interpreting a visual regression."
        )
    elif comparison["status"] == "incomplete":
        warnings.append("Environment evidence is incomplete; compatibility is unknown.")
    for side, document in [("Base", base_result), ("Current", current_result)]:
        if document["inventory_check"] == "unknown":
            warnings.append(side + " font availability is unknown: no complete font inventory.")
        if document["families_absent_from_inventory"]:
            warnings.append(
                side
                + " declared families absent from inventory: "
                + ", ".join(document["families_absent_from_inventory"])
                + ". "
                "Substitution is possible, not confirmed."
            )
        if document["font_inspection"]["theme_references"]:
            warnings.append(side + " has unresolved theme font references.")
    for tool, evidence in environment["tools"].items():
        if evidence["status"] != "available":
            warnings.append(tool + " is not verified in the current environment.")
    synthetic = any(
        item and item.get("source") == "synthetic" for item in [baseline_environment, environment]
    )
    return {
        "schema_version": 1,
        "mode": "preflight",
        "synthetic_environment": synthetic,
        "base": base_result,
        "current": current_result,
        "text": {
            "status": "incomplete"
            if text_truncated
            else ("changed" if base_text != current_text else "no_extracted_text_change"),
            "truncated": text_truncated,
            "diff": text_diff,
        },
        "font_declaration_changes": {
            "added": sorted(current_fonts - base_fonts, key=str.casefold),
            "removed": sorted(base_fonts - current_fonts, key=str.casefold),
        },
        "environment_comparison": comparison,
        "baseline_environment": baseline_environment,
        "environment": environment,
        "warnings": warnings,
        "limitations": LIMITATIONS,
    }


def render_preflight_html(result: Dict[str, Any]) -> str:
    escape = html.escape
    text_status = {
        "changed": "Extracted text changed",
        "no_extracted_text_change": "No extracted text change",
        "incomplete": "Text evidence incomplete",
    }[result["text"]["status"]]
    comparison = result["environment_comparison"]
    statuses = {
        "not_compared": "No baseline environment supplied",
        "changed": "Observed environment drift",
        "same_observed": "Observed environment fields match",
        "incomplete": "Environment evidence incomplete",
    }
    cards = []
    for side in ["base", "current"]:
        doc = result[side]
        inventory = doc["inventory_check"]
        missing = set(doc["families_absent_from_inventory"])
        rows = []
        for declaration in doc["font_inspection"]["declarations"]:
            family = declaration["family"]
            palette = declaration["kind"] == "theme_palette"
            status = (
                "Theme palette · not checked"
                if palette
                else "Unknown"
                if inventory == "unknown"
                else "Absent from inventory"
                if family in missing
                else "Listed in inventory"
            )
            rows.append(
                "<tr><td>{}</td><td>{}</td><td><code>{}</code></td><td>{}</td></tr>".format(
                    escape(family), escape(declaration["role"]), escape(declaration["part"]), status
                )
            )
        references = doc["font_inspection"]["theme_references"]
        theme = "".join(
            "<li><code>{}</code> · <code>{}</code> · {}</li>".format(
                escape(ref["token"]), escape(ref["part"]), escape(ref["role"])
            )
            for ref in references
        )
        embedded = doc["font_inspection"]["embedded_fonts"]
        cards.append(
            """<section><h2>{side} · {name}</h2><p class="hash">SHA-256 {sha}</p>
<p>Font availability: <strong>{inventory}</strong>. Names describe declarations, not actual use.</p>
<div class="table-wrap"><table><thead><tr><th>Family</th><th>Role</th><th>OOXML part</th>
<th>Evidence</th></tr></thead><tbody>{rows}</tbody></table></div>
<details><summary>Unresolved theme references ({count})</summary><ul>{theme}</ul></details>
<p>Embedded-font evidence: {embedded}. This does not establish renderer support.</p></section>
""".format(
                side=side.title(),
                name=escape(doc["name"]),
                sha=doc["sha256"],
                inventory=inventory,
                rows="\n".join(rows)
                or '<tr><td colspan="4">No explicit or theme-palette declarations found.</td></tr>',
                count=len(references),
                theme=theme,
                embedded=escape(", ".join(embedded) or "none detected"),
            )
        )
    warnings = "".join("<li>{}</li>".format(escape(item)) for item in result["warnings"])
    limitations = "".join("<li>{}</li>".format(escape(item)) for item in result["limitations"])
    tool_rows = "".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            escape(name), escape(value["status"]), escape(value.get("version") or "Unknown")
        )
        for name, value in result["environment"]["tools"].items()
    )
    font_changes = result["font_declaration_changes"]
    banner = (
        '<p class="banner">SYNTHETIC DEMO ENVIRONMENTS · These environment snapshots are '
        "test inputs, not observations from a real renderer.</p>"
        if result["synthetic_environment"]
        else ""
    )
    return """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>Office Diff · Preflight evidence</title><style>
:root {{color-scheme:light; --ink:#182e38; --muted:#526570; --line:#d7e0e4; --accent:#176358}}
* {{box-sizing:border-box}} body {{margin:0; background:#f4f6f5;color:var(--ink);
font:16px/1.65 system-ui,sans-serif}} main {{max-width:1150px;margin:auto;padding:38px 24px 72px}}
header {{border-top:5px solid var(--accent);padding-top:24px;margin-bottom:30px}}
.eyebrow {{letter-spacing:.14em;font-size:12px;font-weight:700;color:var(--accent)}}
h1 {{font-size:clamp(30px,5vw,48px);line-height:1.15;margin:12px 0 18px;letter-spacing:-.03em}}
h2 {{font-size:23px;margin:0 0 14px}} p {{margin:10px 0}} .lead
{{max-width:750px;color:var(--muted)}}
section {{background:white;border:1px solid var(--line);padding:24px;margin:20px 0}}
.signals {{display:grid;grid-template-columns:1fr 1fr;gap:14px}} .signal
{{padding:20px;background:#e3eee9}}
.signal strong {{display:block;font-size:22px;line-height:1.3}} .signal span
{{font-size:13px;color:var(--muted)}}
.banner {{background:#fff1c9;border-left:4px solid #9a6920;padding:12px 18px;font-weight:650}}
.warn {{border-left:4px solid #9a6920}} .hash
{{font-size:12px;overflow-wrap:anywhere;color:var(--muted)}}
table {{width:100%;border-collapse:collapse;font-size:14px;text-align:left}} th,td
{{padding:10px 12px;
border-bottom:1px solid var(--line);vertical-align:top}} th {{background:#eef3f1}}
.table-wrap {{overflow-x:auto}} code,pre {{font-family:ui-monospace,monospace;font-size:13px}}
pre {{overflow-x:auto;background:#edf2f1;padding:20px;white-space:pre-wrap;overflow-wrap:anywhere}}
details {{margin-top:18px}} summary {{cursor:pointer;font-weight:600}} li {{margin:8px 0}}
a {{color:var(--accent)}} footer {{color:var(--muted);font-size:13px}}
@media(max-width:650px) {{main {{padding:24px 14px}} section {{padding:18px}} .signals
{{grid-template-columns:1fr}}}}
</style></head><body><main><header><div class="eyebrow">OFFICE DIFF / PREFLIGHT</div>
<h1>What changed in the source?<br>What changed in the environment?</h1>
<p class="lead">Read the evidence before interpreting a visual diff. This report checks DOCX / PPTX
font declarations, extracted text and observed environment fields. It renders no
pages.</p>{banner}</header>
<div class="signals"><div class="signal"><span>SOURCE
EVIDENCE</span><strong>{text_status}</strong></div>
<div class="signal"><span>ENVIRONMENT EVIDENCE</span><strong>{env_status}</strong></div></div>
<section class="warn"><h2>Review notes ({warning_count})</h2><ul>{warnings}</ul>
<p>No warning is proof of visual correctness or a font-caused regression.</p></section>
<section><h2>Source changes</h2><p>Declared families added: <strong>{added}</strong><br>
Declared families removed: <strong>{removed}</strong></p><pre>{text_diff}</pre></section>
{cards}<section><h2>Observed environment</h2><p>Changed fields: {changed_fields}</p>
<p class="hash">Baseline fingerprint: {base_fp}<br>Current fingerprint: {current_fp}</p>
<div class="table-wrap"><table><thead><tr><th>Tool</th><th>Evidence</th><th>Version
output</th></tr></thead>
<tbody>{tools}</tbody></table></div><p>Font inventory: {font_status}. Full machine-readable
snapshots are in
<a href="summary.json">summary.json</a>; the current snapshot is in <a
href="environment.json">environment.json</a>.</p>
</section><section><h2>Limits of this evidence</h2><ul>{limitations}</ul></section>
<footer>Office Diff Action · Local inspection. No telemetry, external scripts or document
upload.</footer>
</main></body></html>""".format(
        banner=banner,
        text_status=text_status,
        env_status=statuses[comparison["status"]],
        warning_count=len(result["warnings"]),
        warnings=warnings or "<li>No warnings recorded.</li>",
        added=escape(", ".join(font_changes["added"]) or "none"),
        removed=escape(", ".join(font_changes["removed"]) or "none"),
        text_diff=escape(
            result["text"]["diff"]
            or (
                "No difference in the extracted prefixes; the remaining text was not checked."
                if result["text"]["truncated"]
                else "No change in extracted text."
            )
        ),
        cards="\n".join(cards),
        changed_fields=escape(", ".join(comparison["changed_fields"]) or "none observed"),
        base_fp=escape(comparison["baseline_fingerprint"] or "not supplied"),
        current_fp=escape(comparison["current_fingerprint"]),
        tools=tool_rows,
        font_status=escape(result["environment"]["fonts"]["status"]),
        limitations=limitations,
    )


def write_preflight(result: Dict[str, Any], output: Path) -> None:
    # CLI prepares a safe, marked output directory before calling this function.
    (output / "summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output / "environment.json").write_text(
        json.dumps(result["environment"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output / "index.html").write_text(render_preflight_html(result), encoding="utf-8")
