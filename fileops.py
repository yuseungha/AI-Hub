"""Copy, move and recycle files on explicit user request.

Rules: never overwrite (a free 'name (2).ext' is chosen instead), never delete
permanently (only the Windows Recycle Bin; failure leaves the file in place),
and refuse agent_lab job records and the running executable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import shutil
import sys

LABELS = {"copy": "복사", "move": "이동", "trash": "휴지통으로 삭제"}


@dataclass
class Result:
    op: str
    done: list[tuple[Path, Path | None]] = field(default_factory=list)
    skipped: list[tuple[Path, str]] = field(default_factory=list)
    failed: list[tuple[Path, str]] = field(default_factory=list)

    def summary(self):
        text = f"{LABELS[self.op]}: 완료 {len(self.done)}개"
        if self.skipped:
            text += f" · 건너뜀 {len(self.skipped)}개"
        if self.failed:
            text += f" · 실패 {len(self.failed)}개"
        return text

    def details(self, limit=15):
        lines = [f"건너뜀 · {path.name}: {reason}" for path, reason in self.skipped]
        lines += [f"실패 · {path.name}: {reason}" for path, reason in self.failed]
        return "\n".join(lines[:limit] + ([f"외 {len(lines) - limit}건"] if len(lines) > limit else []))


def default_trash(path: Path) -> bool:
    """Send one file to the Recycle Bin via Qt (IFileOperation on Windows)."""
    from PySide6.QtCore import QFile
    return bool(QFile.moveToTrash(str(path)))


def running_executable():
    return Path(sys.executable).resolve() if getattr(sys, "frozen", False) else None


def inside(path: Path, folder: Path):
    try:
        return path.resolve().is_relative_to(folder.resolve())
    except OSError:
        return False


def protected_reason(path: Path, root: Path, running: Path | None):
    if inside(path, root / "agent_lab" / "jobs"):
        return "agent_lab 작업 기록은 변경하지 않음"
    if running is not None and path.resolve() == running:
        return "실행 중인 프로그램"
    if path.is_symlink() or not path.is_file():
        return "일반 파일이 아님 또는 없음"
    return None


def free_target(folder: Path, name: str):
    """folder/name, or the first free 'stem (n)suffix' — existing files are never reused."""
    target = folder / name
    stem, suffix = Path(name).stem, Path(name).suffix
    number = 2
    while target.exists():
        target = folder / f"{stem} ({number}){suffix}"
        number += 1
    return target


def check_destination(dest: Path, root: Path):
    if not dest.is_dir():
        return "대상 폴더가 없음"
    if inside(dest, root / "agent_lab" / "jobs"):
        return "agent_lab 작업 기록 폴더로는 보낼 수 없음"
    return None


MAX_NAME_TRIES = 1000


def exclusive_copy(source: Path, folder: Path):
    """Copy into a file this call creates exclusively ('xb'), so a file that appears
    between choosing the name and writing is never overwritten. On failure only the
    file created here is removed."""
    for _ in range(MAX_NAME_TRIES):
        target = free_target(folder, source.name)
        try:
            handle = open(target, "xb")
        except FileExistsError:
            continue  # somebody took the name meanwhile; pick the next free one
        try:
            with handle, open(source, "rb") as reader:
                shutil.copyfileobj(reader, handle)
            shutil.copystat(source, target)
        except OSError:
            target.unlink(missing_ok=True)
            raise
        return target
    raise OSError("사용할 수 있는 새 이름을 찾지 못함")


def exclusive_rename(source: Path, folder: Path):
    """Same-volume move; os.rename refuses an existing target on Windows, so retry
    with the next free name instead of overwriting."""
    for _ in range(MAX_NAME_TRIES):
        target = free_target(folder, source.name)
        try:
            os.rename(source, target)
            return target
        except FileExistsError:
            continue
    raise OSError("사용할 수 있는 새 이름을 찾지 못함")


def copy_files(paths, dest: Path, root: Path, running=None):
    result = Result("copy")
    problem = check_destination(dest, root)
    for path in map(Path, paths):
        reason = problem or protected_reason(path, root, running)
        if reason:
            result.skipped.append((path, reason))
            continue
        try:
            result.done.append((path, exclusive_copy(path, dest)))
        except OSError as error:
            result.failed.append((path, str(error)))
    return result


def move_files(paths, dest: Path, root: Path, running=None):
    result = Result("move")
    problem = check_destination(dest, root)
    for path in map(Path, paths):
        reason = problem or protected_reason(path, root, running)
        if not reason and path.parent.resolve() == dest.resolve():
            reason = "이미 대상 폴더에 있음"
        if reason:
            result.skipped.append((path, reason))
            continue
        try:
            if path.stat().st_dev == dest.stat().st_dev:
                target = exclusive_rename(path, dest)
            else:  # other volume: exclusive copy, remove the original only after a full copy
                target = exclusive_copy(path, dest)
                path.unlink()
            result.done.append((path, target))
        except OSError as error:
            result.failed.append((path, str(error)))
    return result


def trash_files(paths, root: Path, running=None, trash=default_trash):
    result = Result("trash")
    for path in map(Path, paths):
        reason = protected_reason(path, root, running)
        if reason:
            result.skipped.append((path, reason))
            continue
        try:
            ok = trash(path)
        except Exception as error:  # the trash backend must never escalate to a permanent delete
            ok, detail = False, str(error)
        else:
            detail = "휴지통으로 보내지 못함 (파일은 그대로 둠)"
        if ok and not path.exists():
            result.done.append((path, None))
        else:
            result.failed.append((path, detail if not ok else "삭제 후에도 파일이 남아 있음"))
    return result
