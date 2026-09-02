"""Read Office file changes from a Git range."""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .ooxml import SUPPORTED_SUFFIXES

GIT_LFS_POINTER_HEADER = b"version https://git-lfs.github.com/spec/v1\n"


class GitError(RuntimeError):
    pass


@dataclass
class ChangedFile:
    status: str
    old_path: Optional[str]
    new_path: Optional[str]

    @property
    def display_path(self) -> str:
        return self.new_path or self.old_path or "unknown"


def _run_git(repository: Path, arguments: List[str], binary: bool = False):
    result = subprocess.run(
        ["git", "-C", str(repository)] + arguments,
        capture_output=True,
        text=not binary,
    )
    if result.returncode != 0:
        stderr = result.stderr
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        raise GitError((stderr or "Git command failed").strip())
    return result.stdout


def _verify_ref(repository: Path, ref: str) -> None:
    try:
        _run_git(repository, ["rev-parse", "--verify", "{}^{{commit}}".format(ref)])
    except GitError as exc:
        raise GitError(
            "Git ref {!r} is unavailable. Use actions/checkout with fetch-depth: 0.".format(ref)
        ) from exc


def trust_repository_for_ci(repository: Path) -> None:
    """Mark the mounted Actions workspace safe inside the disposable container."""

    result = subprocess.run(
        ["git", "config", "--global", "--add", "safe.directory", str(repository)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise GitError((result.stderr or "Could not configure Git safe.directory").strip())


def collect_changes(repository: Path, base_ref: str, head_ref: str) -> List[ChangedFile]:
    """Return added, modified, deleted, and renamed Office files."""

    _verify_ref(repository, base_ref)
    _verify_ref(repository, head_ref)
    payload = _run_git(
        repository,
        ["diff", "--name-status", "-z", base_ref, head_ref, "--"],
        binary=True,
    )
    tokens = payload.split(b"\0")
    changes: List[ChangedFile] = []
    index = 0
    while index < len(tokens) and tokens[index]:
        status = tokens[index].decode("utf-8", errors="replace")
        index += 1
        code = status[0]
        if code in {"R", "C"}:
            if index + 1 >= len(tokens):
                raise GitError("Unexpected rename record in git diff output")
            old_path = tokens[index].decode("utf-8", errors="surrogateescape")
            new_path = tokens[index + 1].decode("utf-8", errors="surrogateescape")
            index += 2
        else:
            if index >= len(tokens):
                raise GitError("Unexpected path record in git diff output")
            path = tokens[index].decode("utf-8", errors="surrogateescape")
            index += 1
            old_path = None if code == "A" else path
            new_path = None if code == "D" else path
        old_supported = bool(old_path and Path(old_path).suffix.lower() in SUPPORTED_SUFFIXES)
        new_supported = bool(new_path and Path(new_path).suffix.lower() in SUPPORTED_SUFFIXES)
        if code == "R":
            if (
                old_supported
                and new_supported
                and Path(old_path).suffix.lower() == Path(new_path).suffix.lower()
            ):
                changes.append(ChangedFile(status=status, old_path=old_path, new_path=new_path))
            else:
                if old_supported:
                    changes.append(ChangedFile(status="D", old_path=old_path, new_path=None))
                if new_supported:
                    changes.append(ChangedFile(status="A", old_path=None, new_path=new_path))
        elif code == "C":
            if new_supported:
                changes.append(ChangedFile(status="A", old_path=None, new_path=new_path))
        elif old_supported or new_supported:
            changes.append(ChangedFile(status=status, old_path=old_path, new_path=new_path))
    return changes


def materialize(repository: Path, ref: str, path: str, destination: Path) -> Path:
    """Write one file from one Git ref to a temporary path."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = _run_git(repository, ["show", "{}:{}".format(ref, path)], binary=True)
    if payload.startswith(GIT_LFS_POINTER_HEADER):
        raise GitError(
            "{} at {} is stored with Git LFS, which Office Diff does not yet support".format(
                path, ref
            )
        )
    destination.write_bytes(payload)
    return destination
