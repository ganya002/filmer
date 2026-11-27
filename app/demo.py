"""A small shelf of titles so the page can be opened before a real scan."""

from __future__ import annotations

import time
from pathlib import Path

from app.library import Library, make_id, path_key
from app.scan import Found, Video


def _video(folder: str, filename: str, season: int | None = None, episode: int | None = None) -> Video:
    path = Path(folder) / filename
    return Video(
        path=path,
        name=filename,
        stem=Path(filename).stem,
        size=1_000_000_000,
        mtime=time.time(),
        season=season,
        episode=episode,
    )


def seed(library: Library) -> None:
    if library.setting("demo_seeded") == "1":
        return
    movies = [
        ("Inception", 2010, r"D:\Filmer\Inception (2010)", "Inception.2010.1080p.mkv", (3600, 8880)),
        ("Titanic", 1997, r"D:\Filmer\Titanic (1997)", "Titanic.mkv", None),
        ("Flåklypa Grand Prix", 1975, r"D:\Filmer\Flåklypa Grand Prix", "Flaklypa.mkv", None),
        ("Bølgen", 2015, r"D:\Filmer\Bølgen (2015)", "Bolgen.2015.mkv", None),
        ("Interstellar", 2014, r"D:\Filmer\Interstellar (2014)", "Interstellar.mkv", None),
        ("Dune", 2021, r"D:\Filmer\Dune (2021)", "Dune.mkv", None),
        ("The Shawshank Redemption", 1994, r"D:\Filmer\The Shawshank Redemption", "Shawshank.mkv", (8520, 8520)),
        ("Kongen av Bastøy", 2010, r"D:\Filmer\Kongen av Bastøy", "Kongen av Bastoy.mkv", None),
    ]
    ids = {}
    inception_path = ""
    for title, year, folder, filename, progress in movies:
        video = _video(folder, filename)
        found = Found(
            id_path=folder,
            kind="movie",
            container="folder",
            title=title,
            year=year,
            folder=folder,
            videos=[video],
            subtitle_count=1,
        )
        item_id = library.upsert_found(found)
        ids[title] = item_id
        if title == "Inception":
            inception_path = str(video.path)
        if progress and title != "Inception":
            library.set_progress(str(video.path), progress[0], progress[1])

    series = [
        (
            "Beforeigners",
            2019,
            r"D:\Serier\Beforeigners",
            [
                (1, 1, "Beforeigners.S01E01.mkv", (2700, 2700)),
                (1, 2, "Beforeigners.S01E02.mkv", None),
            ],
        ),
        (
            "Breaking Bad",
            2008,
            r"D:\Serier\Breaking Bad",
            [
                (1, 1, "Breaking.Bad.S01E01.mkv", None),
                (1, 2, "Breaking.Bad.S01E02.mkv", None),
                (1, 3, "Breaking.Bad.S01E03.mkv", None),
            ],
        ),
        (
            "Exit",
            2019,
            r"E:\Serier\Exit",
            [
                (1, 1, "Exit.S01E01.mkv", (1200, 2700)),
                (1, 2, "Exit.S01E02.mkv", None),
            ],
        ),
    ]
    for title, year, folder, episodes in series:
        videos = []
        progresses = []
        for season, episode, filename, progress in episodes:
            videos.append(_video(str(Path(folder) / f"Sesong {season}"), filename, season, episode))
            progresses.append(progress)
        found = Found(
            id_path=folder,
            kind="series",
            container="folder",
            title=title,
            year=year,
            folder=folder,
            videos=videos,
            subtitle_count=len(videos),
        )
        library.upsert_found(found)
        for video, progress in zip(videos, progresses):
            if progress:
                library.set_progress(str(video.path), progress[0], progress[1])

    norwegian = library.add_category("Norske filmer")
    for title in ("Flåklypa Grand Prix", "Bølgen", "Kongen av Bastøy"):
        library.set_membership(norwegian["id"], ids[title], True)
    # Touched last, so the home screen offers to resume this one-hour movie.
    library.set_progress(inception_path, 3600, 8880)
    library.set_setting("demo_seeded", "1")


def remember_id(folder: str) -> str:
    return make_id(folder)


def progress_key(path: str) -> str:
    return path_key(path)
