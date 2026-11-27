"""Turn messy release filenames into titles a person can read."""

from __future__ import annotations

import re

VIDEO_EXT = {
    ".mkv", ".mp4", ".avi", ".m4v", ".wmv", ".mov",
    ".mpg", ".mpeg", ".ts", ".m2ts", ".webm",
}
SUB_EXT = {".srt", ".sub", ".ass", ".ssa", ".vtt", ".idx"}

JUNK = {
    "1080p", "720p", "2160p", "480p", "576p", "4k", "uhd", "hdr", "hdr10",
    "bluray", "bdrip", "brrip", "webrip", "webdl", "hdtv", "hdrip", "dvdrip",
    "dvd", "x264", "x265", "h264", "h265", "hevc", "aac", "ac3", "truehd",
    "atmos", "nf", "amzn", "atvp", "dsnp", "hmax", "proper", "repack",
    "extended", "remux", "10bit", "8bit", "norwegian", "nordic", "nor", "nob",
    "multi", "yts", "rarbg", "ettv", "eztv", "internal", "limited", "unrated",
    "remastered", "boxset", "complete", "web",
}

# Folders that hold many unrelated videos. Never recycle these wholesale.
PILE_NAMES = {
    "filmer", "movies", "movie", "film", "downloads", "download", "video",
    "videos", "videoer", "serier", "series", "tv", "tv shows", "desktop",
    "documents", "dokumenter", "skrivebord", "nedlastinger", "media",
    "mine filmer", "my movies", "users", "brukere",
}

_EP_PATTERNS = (
    re.compile(r"(?i)(?:^|[^a-z0-9æøå])s(\d{1,2})[ ._\-]*e(\d{1,3})(?:[^a-z0-9æøå]|$)"),
    re.compile(r"(?i)(?:^|[^a-z0-9æøå])(\d{1,2})x(\d{2,3})(?:[^a-z0-9æøå]|$)"),
    re.compile(r"(?i)sesong\s*(\d{1,2}).{0,24}?episode\s*(\d{1,3})"),
)
_SEASON_DIR = re.compile(r"(?i)^(?:season|sesong)\s*0*(\d{1,2})$|^s0*(\d{1,2})$")
_PART = re.compile(r"(?i)(?:^|[\s._\-])(?:cd|part|del|disc)\s*0*(\d{1,2})(?:[\s._\-]|$)")
_YEAR = re.compile(r"^(19|20)\d{2}$")
_AUDIO = re.compile(r"^(ddp|dts|aac|ac3|eac3|dd)\d*$")


def parse_episode(name: str) -> tuple[int, int] | None:
    for pattern in _EP_PATTERNS:
        match = pattern.search(name)
        if match:
            nums = [int(g) for g in match.groups() if g]
            if len(nums) >= 2:
                return nums[0], nums[1]
    return None


def season_number(dirname: str) -> int | None:
    match = _SEASON_DIR.fullmatch(dirname.strip())
    if not match:
        return None
    raw = next(g for g in match.groups() if g)
    return int(raw)


def part_number(stem: str) -> int | None:
    match = _PART.search(stem)
    if not match:
        return None
    return int(match.group(1))


def is_extra(name: str) -> bool:
    folded = name.lower().replace("_", " ").replace(".", " ")
    keys = (
        "sample", "trailer", "featurette", "blooper", "teaser",
        "deleted scene", "behind the scene",
    )
    return any(key in folded for key in keys)


def clean_title(stem: str) -> tuple[str, int | None]:
    """Return (title, year) from a file or folder name."""
    text = re.sub(r"[._]+", " ", stem)
    text = re.sub(r"\s+", " ", text).strip()
    cut = re.search(r"(?i)\bs\d{1,2}\s*e\d{1,3}\b|\b\d{1,2}x\d{2,3}\b", text)
    if cut:
        text = text[: cut.start()].strip()
    year: int | None = None
    kept: list[str] = []
    for token in text.split(" "):
        bare = re.sub(r"[^0-9a-zA-ZæøåÆØÅ+]", "", token).lower()
        if not bare:
            continue
        if _YEAR.fullmatch(bare):
            if year is None:
                year = int(bare)
            break
        if bare in JUNK or _AUDIO.fullmatch(bare):
            break
        if re.fullmatch(r"(?:cd|part|del|disc)0*\d{1,2}", bare):
            continue
        kept.append(token.strip("()[]"))
    title = re.sub(r"\s+", " ", " ".join(kept)).strip(" -")
    if not title:
        title = re.sub(r"\s+", " ", text).strip() or stem
    return title, year


def format_duration(seconds: float | int | None) -> str:
    if not seconds or seconds < 30:
        return "under ett minutt" if seconds else "0 min"
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes = rem // 60
    if hours and minutes:
        return f"{hours} t {minutes} min"
    if hours:
        return f"{hours} t"
    if minutes:
        return f"{minutes} min"
    return "under ett minutt"
