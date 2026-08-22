#!/usr/bin/env python3
"""Build and verify a source ZIP from the committed Git tree only."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
import zipfile


PROJECT_NAME = "autogen-azure-architecture-designer"
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_ARCHIVE_CONTENT_BYTES = 10 * 1024 * 1024
DENIED_PARTS = {
    ".git",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".vscode",
    "__pycache__",
    "dist",
    "models",
    "venv",
}
DENIED_SUFFIXES = {
    ".bin",
    ".gguf",
    ".jsonl",
    ".key",
    ".log",
    ".pem",
    ".safetensors",
    ".swo",
    ".swp",
    ".zip",
}
SENSITIVE_CONTENT_PATTERNS = (
    re.compile(rb"/Users/[A-Za-z0-9._-]+/"),
    re.compile(rb"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----"),
    re.compile(rb"AKIA[0-9A-Z]{16}"),
    re.compile(rb"sk-[A-Za-z0-9_-]{20,}"),
)


class ReleaseValidationError(RuntimeError):
    """Raised when the committed tree is unsafe to package."""


@dataclass(frozen=True, slots=True)
class ReleaseArtifact:
    path: Path
    sha256: str
    size_bytes: int
    file_count: int


def _git(repo_root: Path, *arguments: str, text: bool = False) -> str | bytes:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=text,
    )
    return result.stdout


def _ensure_clean_tracked_tree(repo_root: Path) -> None:
    for arguments in (("diff", "--quiet"), ("diff", "--cached", "--quiet")):
        result = subprocess.run(
            ["git", *arguments],
            cwd=repo_root,
            capture_output=True,
        )
        if result.returncode == 1:
            raise ReleaseValidationError(
                "Tracked changes must be committed before building a release"
            )
        if result.returncode != 0:
            raise ReleaseValidationError("Unable to inspect tracked Git state")


def _path_is_denied(path: str) -> bool:
    pure_path = PurePosixPath(path)
    if pure_path.is_absolute() or ".." in pure_path.parts:
        return True
    if any(part in DENIED_PARTS for part in pure_path.parts):
        return True
    if pure_path.parts and pure_path.parts[0] == "results":
        return path != "results/README.md"
    name = pure_path.name
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return True
    return pure_path.suffix.casefold() in DENIED_SUFFIXES


def _tracked_tree(repo_root: Path) -> dict[str, bytes]:
    raw_entries = _git(repo_root, "ls-tree", "-r", "-z", "HEAD")
    if not isinstance(raw_entries, bytes):
        raise ReleaseValidationError("Unexpected Git tree output")
    files: dict[str, bytes] = {}
    total_size = 0
    for raw_entry in raw_entries.split(b"\0"):
        if not raw_entry:
            continue
        metadata, raw_path = raw_entry.split(b"\t", 1)
        mode, object_type, object_id = metadata.decode("ascii").split()
        path = raw_path.decode("utf-8")
        if mode not in {"100644", "100755"} or object_type != "blob":
            raise ReleaseValidationError(f"Unsupported tracked entry: {path}")
        if _path_is_denied(path):
            raise ReleaseValidationError(f"Denied tracked release path: {path}")
        content = _git(repo_root, "cat-file", "blob", object_id)
        if not isinstance(content, bytes):
            raise ReleaseValidationError("Unexpected Git blob output")
        if len(content) > MAX_FILE_BYTES:
            raise ReleaseValidationError(f"Tracked file exceeds size limit: {path}")
        for pattern in SENSITIVE_CONTENT_PATTERNS:
            if pattern.search(content):
                raise ReleaseValidationError(
                    f"Sensitive content pattern found in tracked file: {path}"
                )
        files[path] = content
        total_size += len(content)
    if total_size > MAX_ARCHIVE_CONTENT_BYTES:
        raise ReleaseValidationError("Tracked release content exceeds size limit")
    return files


def _validate_archive(
    archive_path: Path,
    *,
    prefix: str,
    tracked_files: dict[str, bytes],
) -> None:
    expected_names = {f"{prefix}{path}" for path in tracked_files}
    with zipfile.ZipFile(archive_path) as archive:
        file_entries = [entry for entry in archive.infolist() if not entry.is_dir()]
        actual_names = {entry.filename for entry in file_entries}
        if actual_names != expected_names:
            raise ReleaseValidationError("Archive file list differs from committed tree")
        total_size = 0
        for entry in file_entries:
            unix_mode = (entry.external_attr >> 16) & 0o170000
            if unix_mode == 0o120000:
                raise ReleaseValidationError(
                    f"Symbolic link found in archive: {entry.filename}"
                )
            relative_name = entry.filename.removeprefix(prefix)
            content = archive.read(entry)
            if content != tracked_files[relative_name]:
                raise ReleaseValidationError(
                    f"Archive content mismatch: {relative_name}"
                )
            total_size += len(content)
            for pattern in SENSITIVE_CONTENT_PATTERNS:
                if pattern.search(content):
                    raise ReleaseValidationError(
                        f"Sensitive content pattern found in archive: {relative_name}"
                    )
        if total_size > MAX_ARCHIVE_CONTENT_BYTES:
            raise ReleaseValidationError("Archive content exceeds size limit")


def build_release_archive(
    repo_root: Path,
    output_path: Path | None = None,
) -> ReleaseArtifact:
    """Package HEAD only, validate it, and publish without overwriting."""

    repo_root = repo_root.resolve(strict=True)
    _ensure_clean_tracked_tree(repo_root)
    tracked_files = _tracked_tree(repo_root)
    short_commit = str(
        _git(repo_root, "rev-parse", "--short=12", "HEAD", text=True)
    ).strip()
    prefix = f"{PROJECT_NAME}-{short_commit}/"
    if output_path is None:
        destination = repo_root / "dist" / f"{PROJECT_NAME}-{short_commit}.zip"
    else:
        destination = (
            output_path if output_path.is_absolute() else repo_root / output_path
        )
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Refusing to overwrite release archive: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if (
        destination.parent.is_symlink()
        or destination.parent.resolve(strict=True) != destination.parent
    ):
        raise ReleaseValidationError("Release output directory cannot be a symlink")

    temporary_file = tempfile.NamedTemporaryFile(
        prefix=".release-",
        suffix=".zip",
        dir=destination.parent,
        delete=False,
    )
    temporary_path = Path(temporary_file.name)
    temporary_file.close()
    try:
        subprocess.run(
            [
                "git",
                "archive",
                "--format=zip",
                f"--prefix={prefix}",
                f"--output={temporary_path}",
                "HEAD",
            ],
            cwd=repo_root,
            check=True,
        )
        _validate_archive(
            temporary_path,
            prefix=prefix,
            tracked_files=tracked_files,
        )
        os.link(temporary_path, destination, follow_symlinks=False)
    finally:
        temporary_path.unlink(missing_ok=True)

    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    return ReleaseArtifact(
        path=destination,
        sha256=digest,
        size_bytes=destination.stat().st_size,
        file_count=len(tracked_files),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Explicit non-existing ZIP path")
    arguments = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    artifact = build_release_archive(repo_root, arguments.output)
    print(f"archive={artifact.path}")
    print(f"files={artifact.file_count}")
    print(f"bytes={artifact.size_bytes}")
    print(f"sha256={artifact.sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
