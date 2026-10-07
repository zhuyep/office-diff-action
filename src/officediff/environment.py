"""Read-only observations of the local Office rendering environment.

A fingerprint identifies the configuration observed by this module. It does not
prove rendering reproducibility or identify the font a renderer actually used.
"""

import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import unicodedata
from pathlib import Path
from typing import Optional

SCHEMA_VERSION = 1
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_STRING_LENGTH = 512
MAX_FONT_FAMILIES = 10_000
MAX_FONT_HASHES = 10_000
MAX_FONT_PATHS = 10_000
MAX_HASHED_FILES = 2048
MAX_FONT_FILE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_FONT_BYTES = 256 * 1024 * 1024
COMMAND_TIMEOUT_SECONDS = 5
TOOLS = ("libreoffice", "pdftoppm", "pdfinfo", "fontconfig")
PLATFORM_FIELDS = ("system", "release", "machine")
TOOL_STATUSES = {"available", "unavailable", "unknown"}
FONT_STATUSES = {"available", "unavailable", "partial"}
HEX_SHA256 = re.compile(r"[0-9a-fA-F]{64}\Z")


def _text(value, location: str, *, family: bool = False) -> str:
    if not isinstance(value, str) or len(value) > MAX_STRING_LENGTH:
        raise ValueError("{} must be a string of at most 512 characters".format(location))
    normalized = unicodedata.normalize("NFC", " ".join(value.split()))
    if any(unicodedata.category(character) == "Cc" for character in normalized):
        raise ValueError("{} contains control characters".format(location))
    return normalized.casefold() if family else normalized


def _keys(value, expected, location: str) -> None:
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError("{} has missing or unexpected fields".format(location))


def _normalized(payload: dict, *, require_fingerprint: bool) -> dict:
    expected = {"schema_version", "source", "platform", "tools", "fonts"}
    if require_fingerprint or (isinstance(payload, dict) and "fingerprint" in payload):
        expected.add("fingerprint")
    _keys(payload, expected, "environment")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise ValueError("Unsupported environment schema_version; expected 1")
    if payload["source"] not in ("captured", "synthetic"):
        raise ValueError("environment.source must be captured or synthetic")
    _keys(payload["platform"], PLATFORM_FIELDS, "environment.platform")
    observed_platform = {
        field: _text(payload["platform"][field], "platform." + field) for field in PLATFORM_FIELDS
    }
    _keys(payload["tools"], TOOLS, "environment.tools")
    observed_tools = {}
    for name in TOOLS:
        tool = payload["tools"][name]
        _keys(tool, ("status", "version"), "tools." + name)
        if not isinstance(tool["status"], str) or tool["status"] not in TOOL_STATUSES:
            raise ValueError("Invalid tool status for " + name)
        version = tool["version"]
        if version is not None:
            version = _text(version, "tools.{}.version".format(name))
            if not version:
                raise ValueError("Tool versions must be nonempty strings or null")
        if tool["status"] != "available" and version is not None:
            raise ValueError("Only an available tool may have a version")
        observed_tools[name] = {"status": tool["status"], "version": version}
    fonts = payload["fonts"]
    _keys(fonts, ("status", "families", "file_hashes", "unhashed_files"), "fonts")
    if not isinstance(fonts["status"], str) or fonts["status"] not in FONT_STATUSES:
        raise ValueError("Invalid fonts.status")
    families = fonts["families"]
    hashes = fonts["file_hashes"]
    if not isinstance(families, list) or len(families) > MAX_FONT_FAMILIES:
        raise ValueError("fonts.families must be a list of at most 10000 entries")
    families = [_text(item, "fonts.families entry", family=True) for item in families]
    if any(not family for family in families):
        raise ValueError("Font families must be nonempty")
    if not isinstance(hashes, list) or len(hashes) > MAX_FONT_HASHES:
        raise ValueError("fonts.file_hashes must be a list of at most 10000 entries")
    if any(not isinstance(item, str) or not HEX_SHA256.fullmatch(item) for item in hashes):
        raise ValueError("Font file hashes must be SHA-256 hexadecimal strings")
    unhashed = fonts["unhashed_files"]
    if type(unhashed) is not int or not 0 <= unhashed <= 1_000_000:
        raise ValueError("fonts.unhashed_files must be an integer from 0 to 1000000")
    if fonts["status"] == "available" and unhashed:
        raise ValueError("Available font inventories cannot contain unhashed files")
    if fonts["status"] == "unavailable" and (families or hashes or unhashed):
        raise ValueError("Unavailable font inventories cannot contain observations")
    result = {
        "schema_version": SCHEMA_VERSION,
        "source": payload["source"],
        "platform": observed_platform,
        "tools": observed_tools,
        "fonts": {
            "status": fonts["status"],
            "families": sorted(set(families)),
            "file_hashes": sorted({item.lower() for item in hashes}),
            "unhashed_files": unhashed,
        },
    }
    fingerprint = _fingerprint(result)
    if "fingerprint" in payload:
        supplied = payload["fingerprint"]
        if not isinstance(supplied, str) or not HEX_SHA256.fullmatch(supplied):
            raise ValueError("environment.fingerprint must be a SHA-256 hexadecimal string")
        if supplied.lower() != fingerprint:
            raise ValueError("Environment fingerprint does not match its observations")
    result["fingerprint"] = fingerprint
    return result


def _fingerprint(payload: dict) -> str:
    observations = {name: payload[name] for name in ("platform", "tools", "fonts")}
    serialized = json.dumps(
        observations, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def environment_fingerprint(payload: dict) -> str:
    """Hash normalized observations, excluding their source and existing fingerprint.

    Unlike ``load_environment``, this function permits a stale fingerprint so a
    caller can explicitly recalculate it after changing a synthetic fixture.
    """
    if not isinstance(payload, dict):
        raise ValueError("environment must be an object")
    without_fingerprint = {key: value for key, value in payload.items() if key != "fingerprint"}
    return _normalized(without_fingerprint, require_fingerprint=False)["fingerprint"]


def _run(command):
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=COMMAND_TIMEOUT_SECONDS,
        check=False,
    )


def _probe_tool(names, arguments, version_pattern):
    executable = next((found for name in names if (found := shutil.which(name))), None)
    if executable is None:
        return {"status": "unavailable", "version": None}, None
    try:
        result = _run([executable] + arguments)
        output = result.stdout + "\n" + result.stderr
        if result.returncode != 0 or len(output.encode("utf-8")) > MAX_MANIFEST_BYTES:
            return {"status": "unknown", "version": None}, executable
        match = re.search(version_pattern, output, flags=re.MULTILINE | re.IGNORECASE)
        if match:
            version = _text(match.group(0), "tool version")
            return {"status": "available", "version": version}, executable
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass
    return {"status": "unknown", "version": None}, executable


def _hash_font(path: str, remaining_bytes: int):
    """Return (hash, bytes_read), refusing nonregular, oversized or changing files."""
    descriptor = None
    consumed = 0
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            before = os.fstat(stream.fileno())
            budget = min(MAX_FONT_FILE_BYTES, remaining_bytes)
            if not stat.S_ISREG(before.st_mode) or before.st_size > budget:
                return None, 0
            digest = hashlib.sha256()
            while consumed <= budget:
                chunk = stream.read(min(1024 * 1024, budget - consumed + 1))
                if not chunk:
                    break
                consumed += len(chunk)
                if consumed > budget:
                    return None, consumed
                digest.update(chunk)
            after = os.fstat(stream.fileno())
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                return None, consumed
            if consumed != before.st_size:
                return None, consumed
            return digest.hexdigest(), consumed
    except (OSError, ValueError):
        return None, consumed
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _capture_fonts(executable: Optional[str]) -> dict:
    fonts = {"status": "unavailable", "families": [], "file_hashes": [], "unhashed_files": 0}
    if executable is None:
        return fonts
    fonts["status"] = "partial"
    try:
        result = _run([executable, "--format=%{file}\t%{family}\n"])
    except (OSError, subprocess.TimeoutExpired):
        return fonts
    if result.returncode != 0:
        return fonts
    output = result.stdout.encode("utf-8")
    partial = len(output) > MAX_MANIFEST_BYTES
    if partial:
        # Only consume complete rows from bounded output.
        output = output[:MAX_MANIFEST_BYTES].rsplit(b"\n", 1)[0]
    families = set()
    paths = set()
    for row in output.decode("utf-8", errors="replace").splitlines():
        if not row.strip():
            continue
        path, separator, aliases = row.partition("\t")
        if not separator or not path or len(path) > 4096 or not os.path.isabs(path):
            partial = True
            continue
        if len(paths) < MAX_FONT_PATHS or path in paths:
            paths.add(path)
        else:
            partial = True
        for alias in aliases.split(","):
            try:
                family = _text(alias, "font family", family=True)
            except ValueError:
                partial = True
                continue
            if not family:
                partial = True
            elif len(families) < MAX_FONT_FAMILIES or family in families:
                families.add(family)
            else:
                partial = True
    hashes = set()
    consumed = 0
    unhashed = 0
    for index, path in enumerate(sorted(paths)):
        if index >= MAX_HASHED_FILES or consumed >= MAX_TOTAL_FONT_BYTES:
            unhashed += 1
            continue
        digest, bytes_read = _hash_font(path, MAX_TOTAL_FONT_BYTES - consumed)
        consumed += bytes_read
        if digest is None:
            unhashed += 1
        else:
            hashes.add(digest)
    fonts.update(
        status="partial" if partial or unhashed else "available",
        families=sorted(families),
        file_hashes=sorted(hashes),
        unhashed_files=unhashed,
    )
    return fonts


def capture_environment() -> dict:
    """Observe tool versions and fontconfig's inventory without installing anything."""
    configurations = (
        ("libreoffice", ("soffice", "libreoffice"), ["--version"], r"^LibreOffice [^\r\n]+"),
        ("pdftoppm", ("pdftoppm",), ["-v"], r"^pdftoppm version [^\r\n]+"),
        ("pdfinfo", ("pdfinfo",), ["-v"], r"^pdfinfo version [^\r\n]+"),
        ("fontconfig", ("fc-list",), ["--version"], r"^fontconfig version [^\r\n]+"),
    )
    observed_tools = {}
    fontconfig = None
    for name, names, arguments, pattern in configurations:
        observed_tools[name], executable = _probe_tool(names, arguments, pattern)
        if name == "fontconfig":
            fontconfig = executable
    payload = {
        "schema_version": SCHEMA_VERSION,
        "source": "captured",
        "platform": {field: getattr(platform, field)() for field in PLATFORM_FIELDS},
        "tools": observed_tools,
        "fonts": _capture_fonts(fontconfig),
    }
    return _normalized(payload, require_fingerprint=False)


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field: " + key)
        result[key] = value
    return result


def load_environment(path) -> dict:
    """Load a bounded schema-v1 snapshot and verify its normalized fingerprint."""
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(MAX_MANIFEST_BYTES + 1)
        if len(raw) > MAX_MANIFEST_BYTES:
            raise ValueError("Environment manifest exceeds the 4 MiB size limit")
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_keys)
        return _normalized(payload, require_fingerprint=True)
    except (OSError, UnicodeError, RecursionError) as error:
        raise ValueError("Could not read environment manifest: {}".format(error)) from error


def _incomplete_fields(environment: dict) -> list:
    missing = [
        "platform." + field for field in PLATFORM_FIELDS if not environment["platform"][field]
    ]
    for name in TOOLS:
        tool = environment["tools"][name]
        if tool["status"] != "available" or tool["version"] is None:
            missing.append("tools." + name)
    if environment["fonts"]["status"] != "available":
        missing.append("fonts")
    return missing


def compare_environments(base: Optional[dict], current: dict) -> dict:
    """Compare evidence, keeping unknown inventories distinct from compatibility."""
    current = _normalized(current, require_fingerprint=True)
    limitations = [
        "This fingerprint describes observed configuration; it does not guarantee reproducibility.",
        "Fontconfig inventory does not identify fonts actually selected by the Office renderer.",
        "Font hashes describe observed file contents; paths and selection order are omitted.",
    ]
    result = {
        "status": "not_compared",
        "changed_fields": [],
        "baseline_fingerprint": None,
        "current_fingerprint": current["fingerprint"],
        "limitations": limitations,
    }
    if base is None:
        if _incomplete_fields(current):
            limitations.append(
                "Current observations are incomplete: " + ", ".join(_incomplete_fields(current))
            )
        if current["source"] == "synthetic":
            limitations.append(
                "Current observations are synthetic fixture data, not a machine capture."
            )
        limitations.append("No baseline environment was supplied.")
        return result
    base = _normalized(base, require_fingerprint=True)
    result["baseline_fingerprint"] = base["fingerprint"]
    changed = result["changed_fields"]
    for field in PLATFORM_FIELDS:
        before, after = base["platform"][field], current["platform"][field]
        if before and after and before != after:
            changed.append("platform." + field)
    for name in TOOLS:
        before, after = base["tools"][name], current["tools"][name]
        if "unknown" not in (before["status"], after["status"]):
            if before["status"] != after["status"]:
                changed.append("tools.{}.status".format(name))
            elif before["version"] and after["version"] and before["version"] != after["version"]:
                changed.append("tools.{}.version".format(name))
    if base["fonts"]["status"] == current["fonts"]["status"] == "available":
        for field in ("families", "file_hashes"):
            if base["fonts"][field] != current["fonts"][field]:
                changed.append("fonts." + field)
    incomplete = False
    for label, environment in (("Baseline", base), ("Current", current)):
        missing = _incomplete_fields(environment)
        if missing:
            incomplete = True
            limitations.append(label + " observations are incomplete: " + ", ".join(missing))
        if environment["source"] == "synthetic":
            limitations.append(
                label + " observations are synthetic fixture data, not a machine capture."
            )
    result["status"] = "changed" if changed else ("incomplete" if incomplete else "same_observed")
    return result
