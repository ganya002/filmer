"""Find movie folders and series on a drive without walking system folders."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.titles import (
    PILE_NAMES,
    SUB_EXT,
    VIDEO_EXT,
    clean_title,
    is_extra,
    parse_episode,
    part_number,
    season_number,
)

SKIP_DIRS = {
    "windows", "program files", "program files (x86)", "programdata",
    "$recycle.bin", "system volume information", "recovery", "perflogs",
    "node_modules", "appdata", "application data", "windows.old",
    "intel", "nvidia", "amd", "boot", "efi", ".git",
    "python", "python311", "python312", "python313",
}

MIN_FEATURE = 40 * 1024 * 1024


@dataclass
class Video:
    path: Path
    name: str
    stem: str
    size: int
    mtime: float
    season: int | None = None
    episode: int | None = None
    part: int | None = None


@dataclass
class Found:
    id_path: str
    kind: str
    container: str
    title: str
    year: int | None
    folder: str
    videos: list[Video] = field(default_factory=list)
    subtitle_count: int = 0


def keep_dir(name: str) -> bool:
    folded = name.casefold()
    if folded.startswith("."):
        return False
    return folded not in SKIP_DIRS


def _same(a: Path, b: Path) -> bool:
    return os.path.normcase(os.path.normpath(str(a))) == os.path.normcase(os.path.normpath(str(b)))


def title_folder_for(video: Path, root: Path) -> Path:
    parent = video.parent
    if season_number(parent.name) is not None and not _same(parent, root):
        return parent.parent
    return parent


def primary_videos(videos: list[Video]) -> list[Video]:
    pool = [v for v in videos if not is_extra(v.name)] or list(videos)
    if not pool:
        return []
    largest = max(v.size for v in pool)
    if largest >= MIN_FEATURE:
        big = [v for v in pool if v.size >= MIN_FEATURE]
        if big:
            pool = big
            largest = max(v.size for v in pool)
    if len(pool) >= 2 and all(part_number(v.stem) for v in pool):
        return sorted(pool, key=lambda v: part_number(v.stem) or 0)
    if len(pool) >= 2:
        leaders = [v for v in pool if v.size >= largest * 0.4]
        if len(leaders) == 1 and not any(parse_episode(v.name) for v in pool):
            return leaders
    return pool


def _episode_fields(video: Video, folder: Path) -> None:
    parsed = parse_episode(video.name)
    if parsed:
        video.season, video.episode = parsed
    parent = video.path.parent
    while True:
        number = season_number(parent.name)
        if number is not None:
            if video.season is None:
                video.season = number
            break
        if _same(parent, folder) or parent == parent.parent:
            break
        parent = parent.parent
    if video.episode is None and video.season is not None:
        match = re.search(r"(?i)(?:episode\s*|^e|^)(\d{1,3})$", video.stem.strip())
        if not match:
            match = re.search(r"(?i)(?:^|\s)(\d{1,3})$", video.stem.strip())
        if match:
            video.episode = int(match.group(1))
    video.part = part_number(video.stem)


def _fill_episode_numbers(videos: list[Video]) -> None:
    grouped: dict[int, list[Video]] = {}
    for video in videos:
        if video.season is not None and video.episode is None:
            grouped.setdefault(video.season, []).append(video)
    for group in grouped.values():
        ordered = sorted(group, key=lambda video: video.name.casefold())
        for index, video in enumerate(ordered, start=1):
            video.episode = index


def _sort_videos(videos: list[Video]) -> list[Video]:
    return sorted(
        videos,
        key=lambda v: (v.season or 0, v.episode or 0, v.part or 0, v.name.casefold()),
    )


def classify_group(folder: Path, root: Path, videos: list[Video], subtitle_count: int) -> list[Found]:
    chosen = primary_videos(videos)
    if not chosen:
        return []
    for video in chosen:
        _episode_fields(video, folder)
    _fill_episode_numbers(chosen)
    pile = folder.name.casefold() in PILE_NAMES or _same(folder, root)
    episodic = [v for v in chosen if v.episode is not None]
    if len(episodic) >= 2:
        show, year = clean_title(folder.name)
        if pile:
            show = clean_title(episodic[0].stem)[0] or show
        return [
            Found(
                id_path=str(folder),
                kind="series",
                container="file" if pile else "folder",
                title=show,
                year=year,
                folder=str(folder),
                videos=_sort_videos(episodic),
                subtitle_count=subtitle_count,
            )
        ]
    if len(chosen) == 1:
        video = chosen[0]
        if pile:
            title, year = clean_title(video.stem)
            container = "file"
            id_path = str(video.path)
        else:
            title, year = clean_title(folder.name)
            file_title, file_year = clean_title(video.stem)
            if not title or title.casefold() in PILE_NAMES:
                title = file_title
            year = year or file_year
            container = "folder"
            id_path = str(folder)
        return [
            Found(
                id_path=id_path,
                kind="movie",
                container=container,
                title=title,
                year=year,
                folder=str(folder if container == "folder" else video.path.parent),
                videos=chosen,
                subtitle_count=subtitle_count if container == "folder" else 0,
            )
        ]
    titles = {clean_title(v.stem)[0].casefold() for v in chosen}
    parts = [v for v in chosen if v.part]
    if not pile and (len(titles) == 1 or (parts and len(parts) == len(chosen))):
        title, year = clean_title(folder.name)
        return [
            Found(
                id_path=str(folder),
                kind="movie",
                container="folder",
                title=title,
                year=year,
                folder=str(folder),
                videos=_sort_videos(chosen),
                subtitle_count=subtitle_count,
            )
        ]
    found: list[Found] = []
    for video in chosen:
        title, year = clean_title(video.stem)
        found.append(
            Found(
                id_path=str(video.path),
                kind="movie",
                container="file",
                title=title,
                year=year,
                folder=str(video.path.parent),
                videos=[video],
                subtitle_count=0,
            )
        )
    return found


def scan_root(root: Path, on_dir=None) -> list[Found]:
    root = Path(root)
    if not root.exists():
        return []
    groups: dict[str, list[Video]] = {}
    folders: dict[str, Path] = {}
    subs: dict[str, int] = {}

    stack = [root]
    while stack:
        current = stack.pop()
        if on_dir:
            on_dir(str(current))
        try:
            entries = list(os.scandir(current))
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if keep_dir(entry.name):
                        stack.append(Path(entry.path))
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                ext = os.path.splitext(entry.name)[1].lower()
                if ext in SUB_EXT:
                    parent = str(Path(entry.path).parent)
                    subs[parent] = subs.get(parent, 0) + 1
                    continue
                if ext not in VIDEO_EXT:
                    continue
                stat = entry.stat()
                path = Path(entry.path)
                video = Video(
                    path=path,
                    name=entry.name,
                    stem=Path(entry.name).stem,
                    size=stat.st_size,
                    mtime=stat.st_mtime,
                )
                folder = title_folder_for(path, root)
                key = os.path.normcase(os.path.normpath(str(folder)))
                groups.setdefault(key, []).append(video)
                folders[key] = folder
            except OSError:
                continue

    found: list[Found] = []
    for key, videos in groups.items():
        folder = folders[key]
        sub_count = 0
        prefix = key if key.endswith(os.sep) else key + os.sep
        for sub_dir, count in subs.items():
            norm = os.path.normcase(os.path.normpath(sub_dir))
            if norm == key or norm.startswith(prefix):
                sub_count += count
        found.extend(classify_group(folder, root, videos, sub_count))
    found.sort(key=lambda item: item.title.casefold())
    return found


def auto_roots() -> list[str]:
    """Folders worth scanning. On Windows: the user's media folders and every other disk."""
    if os.name != "nt":
        return []
    roots: list[str] = []
    home = Path.home()
    for name in (
        "Videos", "Video", "Videoer", "Downloads", "Nedlastinger",
        "Desktop", "Skrivebord", "Documents", "Dokumenter",
        "Filmer", "Movies", "Serier",
    ):
        candidate = home / name
        if candidate.is_dir():
            roots.append(str(candidate))
    for name in ("Filmer", "Movies", "Serier", "Video", "Videoer"):
        candidate = Path(f"C:\\{name}")
        if candidate.is_dir():
            roots.append(str(candidate))
    import ctypes
    import string

    kernel = ctypes.windll.kernel32
    for letter in string.ascii_uppercase:
        if letter == "C":
            continue
        drive = f"{letter}:\\"
        kind = int(kernel.GetDriveTypeW(drive))
        if kind in (2, 3):
            roots.append(drive)
    # Preserve order, drop duplicates.
    seen: set[str] = set()
    unique: list[str] = []
    for root in roots:
        key = os.path.normcase(os.path.normpath(root))
        if key in seen:
            continue
        seen.add(key)
        unique.append(root)
    return unique
