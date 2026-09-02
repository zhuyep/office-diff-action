"""Command-line interface for direct and GitHub Action comparisons."""

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

from . import __version__
from .compare import compare_documents
from .git_changes import GitError, collect_changes, materialize, trust_repository_for_ci
from .models import RunSummary
from .report import write_reports

OUTPUT_MARKER = ".office-diff-output"
GENERATED_ENTRIES = ("documents", "index.html", "report.md", "summary.json")
MAX_DOCUMENTS_PER_RUN = 20
MAX_REPORT_BYTES = 768 * 1024 * 1024


def _dpi(value: str) -> int:
    number = int(value)
    if not 36 <= number <= 300:
        raise argparse.ArgumentTypeError("must be between 36 and 300")
    return number


def _pixel_threshold(value: str) -> int:
    number = int(value)
    if not 0 <= number <= 255:
        raise argparse.ArgumentTypeError("must be between 0 and 255")
    return number


def _boolean(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise argparse.ArgumentTypeError("must be true or false")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="office-diff",
        description="Render and review visual changes in DOCX and PPTX files.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    compare_parser = subparsers.add_parser("compare", help="compare two Office files")
    compare_parser.add_argument("base", type=Path)
    compare_parser.add_argument("current", type=Path)
    compare_parser.add_argument("--output", type=Path, default=Path("office-diff-report"))
    compare_parser.add_argument("--dpi", type=_dpi, default=110)
    compare_parser.add_argument("--pixel-threshold", type=_pixel_threshold, default=16)

    action_parser = subparsers.add_parser("action", help="compare Office files in a Git range")
    action_parser.add_argument("--repository", type=Path, default=Path.cwd())
    action_parser.add_argument("--base-ref", required=True)
    action_parser.add_argument("--head-ref", default="HEAD")
    action_parser.add_argument("--output", type=Path, default=Path("office-diff-report"))
    action_parser.add_argument("--dpi", type=_dpi, default=110)
    action_parser.add_argument("--pixel-threshold", type=_pixel_threshold, default=16)
    action_parser.add_argument(
        "--allow-render-errors", type=_boolean, nargs="?", const=True, default=False
    )
    return parser


def _validate_document(path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_file():
        raise ValueError("Document does not exist: {}".format(path))
    return resolved


def _prepare_output(output: Path, repository: Optional[Path] = None) -> Path:
    """Prepare a report directory without recursively deleting an arbitrary path."""

    lexical = Path(os.path.abspath(os.fspath(output)))
    if lexical.is_symlink():
        raise ValueError("Refusing a symlinked Office Diff output directory")
    resolved = lexical.resolve()
    forbidden = {Path(resolved.anchor), Path.home().resolve(), Path.cwd().resolve()}
    if resolved in forbidden:
        raise ValueError("Refusing to use a broad directory as report output: {}".format(resolved))
    if repository is not None:
        if any(ord(character) < 32 or ord(character) == 127 for character in os.fspath(output)):
            raise ValueError("Action output path cannot contain control characters")
        repository_lexical = Path(os.path.abspath(os.fspath(repository)))
        try:
            lexical_relative = lexical.relative_to(repository_lexical)
        except ValueError as exc:
            raise ValueError("Action output must stay inside the repository") from exc
        if lexical_relative == Path("."):
            raise ValueError("Action output cannot be the repository root")
        cursor = repository_lexical
        for part in lexical_relative.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise ValueError("Action output path cannot contain symlinks")
        repository = repository_lexical.resolve()
        try:
            resolved.relative_to(repository)
        except ValueError as exc:
            raise ValueError("Action output must stay inside the repository") from exc

    marker = resolved / OUTPUT_MARKER
    if marker.is_symlink():
        raise ValueError("Refusing a symlinked Office Diff output marker")
    if resolved.exists():
        if not resolved.is_dir():
            raise ValueError("Report output is not a directory: {}".format(resolved))
        if any(resolved.iterdir()) and not marker.is_file():
            raise ValueError(
                "Refusing to overwrite a non-empty directory not created by Office Diff: {}".format(
                    resolved
                )
            )
        if marker.is_file():
            for name in GENERATED_ENTRIES:
                target = resolved / name
                if target.is_symlink() or target.is_file():
                    target.unlink()
                elif target.is_dir():
                    shutil.rmtree(target)
    else:
        resolved.mkdir(parents=True)
    descriptor, temporary_marker = tempfile.mkstemp(
        prefix=".office-diff-output-", dir=str(resolved)
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write("office-diff {}\n".format(__version__))
        os.replace(temporary_marker, marker)
    except BaseException:
        try:
            os.unlink(temporary_marker)
        except FileNotFoundError:
            pass
        raise
    return resolved


def _write_github_files(summary: RunSummary, output_dir: Path, repository: Path) -> None:
    relative_report = (output_dir / "index.html").relative_to(repository).as_posix()
    relative_output = output_dir.relative_to(repository).as_posix()
    for value in (relative_report, relative_output):
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("GitHub output values cannot contain control characters")
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as stream:
            stream.write("report-path={}\n".format(relative_report))
            stream.write("documents={}\n".format(len(summary.documents)))
            stream.write("changed-pages={}\n".format(summary.changed_pages))
            stream.write("errors={}\n".format(summary.error_count))
    github_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if github_summary:
        with open(github_summary, "a", encoding="utf-8") as stream:
            stream.write("# Office Diff\n\n")
            stream.write("`{}` → `{}`\n\n".format(summary.base_ref, summary.head_ref))
            stream.write("| Documents | Changed pages/slides | Errors |\n")
            stream.write("|---:|---:|---:|\n")
            stream.write(
                "| {} | {} | {} |\n\n".format(
                    len(summary.documents), summary.changed_pages, summary.error_count
                )
            )
            if summary.documents:
                message = "Upload `{}` as an artifact to open the visual report.\n"
                stream.write(message.format(relative_output))
            else:
                stream.write("No changed `.docx` or `.pptx` files were found.\n")


def _compare_command(args: argparse.Namespace) -> int:
    base = _validate_document(args.base)
    current = _validate_document(args.current)
    output = _prepare_output(args.output)
    document = compare_documents(
        base,
        current,
        current.name,
        output,
        dpi=args.dpi,
        pixel_threshold=args.pixel_threshold,
        max_output_bytes=MAX_REPORT_BYTES,
    )
    summary = RunSummary(base_ref=str(base), head_ref=str(current), documents=[document])
    write_reports(summary, output)
    print("Visual report: {}".format(output / "index.html"))
    return 1 if summary.error_count else 0


def _action_command(args: argparse.Namespace) -> int:
    repository = args.repository.resolve()
    if os.environ.get("GITHUB_ACTIONS") == "true":
        trust_repository_for_ci(repository)
    changes = collect_changes(repository, args.base_ref, args.head_ref)
    if len(changes) > MAX_DOCUMENTS_PER_RUN:
        raise ValueError(
            "Refusing to render {} documents; the per-run limit is {}".format(
                len(changes), MAX_DOCUMENTS_PER_RUN
            )
        )
    output = args.output if args.output.is_absolute() else repository / args.output
    output = _prepare_output(output, repository=repository)
    documents = []
    with tempfile.TemporaryDirectory(prefix="officediff-git-") as temporary:
        temporary_root = Path(temporary)
        for index, change in enumerate(changes):
            suffix = Path(change.display_path).suffix.lower()
            base = None
            current = None
            if change.old_path:
                base = materialize(
                    repository,
                    args.base_ref,
                    change.old_path,
                    temporary_root / "{}-base{}".format(index, suffix),
                )
            if change.new_path:
                current = materialize(
                    repository,
                    args.head_ref,
                    change.new_path,
                    temporary_root / "{}-current{}".format(index, suffix),
                )
            document = compare_documents(
                base,
                current,
                change.display_path,
                output,
                dpi=args.dpi,
                pixel_threshold=args.pixel_threshold,
                max_output_bytes=MAX_REPORT_BYTES,
            )
            document.git_status = change.status
            document.previous_path = change.old_path if change.old_path != change.new_path else None
            change_code = change.status[0]
            document.change_type = {
                "A": "added",
                "D": "deleted",
                "M": "modified",
                "R": "renamed",
                "C": "copied",
            }.get(change_code, "changed")
            if document.change_type in {"renamed", "copied"} and document.status == "unchanged":
                document.status = document.change_type
            documents.append(document)
    summary = RunSummary(
        base_ref=args.base_ref,
        head_ref=args.head_ref,
        documents=documents,
    )
    write_reports(summary, output)
    _write_github_files(summary, output, repository)
    print("Reviewed {} Office document(s).".format(len(documents)))
    print("Visual report: {}".format(output / "index.html"))
    if summary.error_count and not args.allow_render_errors:
        return 1
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "compare":
            return _compare_command(args)
        return _action_command(args)
    except (GitError, OSError, ValueError) as exc:
        print("office-diff: {}".format(exc), file=sys.stderr)
        return 2
