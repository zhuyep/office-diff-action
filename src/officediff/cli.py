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


def _positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
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
    compare_parser.add_argument("--dpi", type=_positive_int, default=110)
    compare_parser.add_argument("--pixel-threshold", type=int, default=16)

    action_parser = subparsers.add_parser("action", help="compare Office files in a Git range")
    action_parser.add_argument("--repository", type=Path, default=Path.cwd())
    action_parser.add_argument("--base-ref", required=True)
    action_parser.add_argument("--head-ref", default="HEAD")
    action_parser.add_argument("--output", type=Path, default=Path("office-diff-report"))
    action_parser.add_argument("--dpi", type=_positive_int, default=110)
    action_parser.add_argument("--pixel-threshold", type=int, default=16)
    action_parser.add_argument(
        "--allow-render-errors", type=_boolean, nargs="?", const=True, default=False
    )
    return parser


def _validate_document(path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_file():
        raise ValueError("Document does not exist: {}".format(path))
    return resolved


def _write_github_files(summary: RunSummary, output_dir: Path) -> None:
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as stream:
            stream.write("report-path={}\n".format((output_dir / "index.html").resolve()))
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
                stream.write("Upload `{}` as an artifact to open the visual report.\n".format(output_dir))
            else:
                stream.write("No changed `.docx` or `.pptx` files were found.\n")


def _compare_command(args: argparse.Namespace) -> int:
    base = _validate_document(args.base)
    current = _validate_document(args.current)
    output = args.output.resolve()
    if output.exists():
        shutil.rmtree(output)
    document = compare_documents(
        base,
        current,
        current.name,
        output,
        dpi=args.dpi,
        pixel_threshold=args.pixel_threshold,
    )
    summary = RunSummary(base_ref=str(base), head_ref=str(current), documents=[document])
    write_reports(summary, output)
    print("Visual report: {}".format(output / "index.html"))
    return 1 if summary.error_count else 0


def _action_command(args: argparse.Namespace) -> int:
    repository = args.repository.resolve()
    if os.environ.get("GITHUB_ACTIONS") == "true":
        trust_repository_for_ci(repository)
    output = args.output if args.output.is_absolute() else repository / args.output
    output = output.resolve()
    if output.exists():
        shutil.rmtree(output)
    changes = collect_changes(repository, args.base_ref, args.head_ref)
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
            documents.append(
                compare_documents(
                    base,
                    current,
                    change.display_path,
                    output,
                    dpi=args.dpi,
                    pixel_threshold=args.pixel_threshold,
                )
            )
    summary = RunSummary(
        base_ref=args.base_ref,
        head_ref=args.head_ref,
        documents=documents,
    )
    write_reports(summary, output)
    _write_github_files(summary, output)
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
