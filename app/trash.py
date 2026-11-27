"""Move a movie folder, or one loose file plus its subtitles, to the trash."""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

from app.titles import SUB_EXT

class TrashError(Exception):
    pass


def is_drive_root(path: Path) -> bool:
    resolved = Path(os.path.abspath(path))
    return resolved.parent == resolved or os.path.normcase(
        os.path.normpath(str(resolved))
    ) == os.path.normcase(os.path.normpath(resolved.anchor))


def assert_safe(path: Path, scan_roots: list[str]) -> Path:
    if path.is_symlink():
        raise TrashError("Mappen er en snarvei. Den ble ikke lagt i papirkurven.")
    if is_drive_root(path):
        raise TrashError("Kan ikke legge en hel disk i papirkurven.")
    target = os.path.normcase(os.path.normpath(os.path.abspath(path)))
    for root in scan_roots:
        if not root:
            continue
        root_key = os.path.normcase(os.path.normpath(os.path.abspath(root)))
        if target == root_key:
            raise TrashError("Kan ikke legge hele søkemappen i papirkurven.")
    return Path(os.path.abspath(path))


def sidecars(video: Path) -> list[Path]:
    parent = video.parent
    if not parent.is_dir():
        return []
    stem = video.stem.casefold()
    found = []
    try:
        children = list(parent.iterdir())
    except OSError:
        return []
    for child in children:
        if not child.is_file() or child.is_symlink():
            continue
        if child.suffix.lower() not in SUB_EXT:
            continue
        if child.stem.casefold().startswith(stem):
            found.append(child)
    return found


def send_to_trash(path: Path) -> None:
    override = os.environ.get("MINEFILMER_TRASH_DIR")
    if override:
        _move_to_dir(path, Path(override))
        return
    if os.name == "nt":
        _windows_recycle(path)
        return
    _xdg_trash(path)


def _move_to_dir(path: Path, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / path.name
    if target.exists():
        target = dest_dir / f"{path.stem}-{int(time.time())}{path.suffix}"
    shutil.move(str(path), str(target))


def _xdg_trash(path: Path) -> None:
    data_home = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
    root = Path(data_home) / "Trash"
    files = root / "files"
    info = root / "info"
    files.mkdir(parents=True, exist_ok=True)
    info.mkdir(parents=True, exist_ok=True)
    dest = files / path.name
    if dest.exists():
        dest = files / f"{path.stem}-{int(time.time())}{path.suffix}"
    original = os.path.abspath(path)
    shutil.move(original, str(dest))
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    (info / (dest.name + ".trashinfo")).write_text(
        f"[Trash Info]\nPath={original}\nDeletionDate={stamp}\n",
        encoding="utf-8",
    )


def _windows_recycle(path: Path) -> None:
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", ctypes.c_uint),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", ctypes.c_ushort),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    FO_DELETE = 3
    FOF_SILENT = 0x0004
    FOF_NOCONFIRMATION = 0x0010
    FOF_ALLOWUNDO = 0x0040
    FOF_NOERRORUI = 0x0400
    op = SHFILEOPSTRUCTW()
    op.wFunc = FO_DELETE
    op.pFrom = str(path) + "\0\0"
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if result != 0 or op.fAnyOperationsAborted:
        raise TrashError("Windows kunne ikke legge det i papirkurven.")


def trash_item(detail: dict, episode: dict | None, scan_roots: list[str]) -> list[str]:
    """Recycle a whole title folder, or one video plus matching subtitles."""
    if detail.get("container") == "folder" and episode is None:
        folder = assert_safe(Path(detail["folder"]), scan_roots)
        if not folder.exists():
            raise TrashError("Finner ikke mappen. Er disken koblet til?")
        send_to_trash(folder)
        return [str(folder)]

    targets = [episode] if episode else detail.get("episodes") or []
    if not targets:
        raise TrashError("Finner ingen fil å legge i papirkurven.")
    moved: list[str] = []
    for ep in targets:
        video = assert_safe(Path(ep["path"]), scan_roots)
        if not video.exists():
            raise TrashError("Finner ikke filen. Er disken koblet til?")
        if video.is_dir():
            raise TrashError("Forventet en fil, fant en mappe.")
        send_to_trash(video)
        moved.append(str(video))
        for side in sidecars(video):
            try:
                send_to_trash(assert_safe(side, scan_roots))
                moved.append(str(side))
            except TrashError:
                continue
            except OSError:
                continue
    return moved
