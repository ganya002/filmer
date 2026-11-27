"""Download one poster at a time and keep it on disk.

Order: optional TMDB key, then Wikidata / Wikipedia, then TVMaze for series.
No account is required for the default path.
"""

from __future__ import annotations

import json
import queue
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

UA = "MineFilmer/1.0 (personal local movie library)"

BAD_DESC = (
    "album", "soundtrack", "song", "book", "episode", "season ",
    "video game", "pc-spill", "building", "sculpture", "painting",
    "singer", "actress", "actor", "skuespiller", "filmmaker",
    "disambiguation", "pekerside", "list article", "company",
    "virksomhet",
)
GOOD_MOVIE = ("film", "movie")
GOOD_SERIES = ("television", "tv series", "tv-serie", "serie")


def sniff_image(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "image/gif"
    if len(data) > 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def poster_path(data_dir: Path, item_id: str) -> Path:
    return data_dir / "posters" / f"{item_id}.img"


class PosterWorker:
    def __init__(self, library, data_dir: Path):
        self.library = library
        self.data_dir = Path(data_dir)
        (self.data_dir / "posters").mkdir(parents=True, exist_ok=True)
        self._queue: queue.Queue = queue.Queue()
        self._queued: set[str] = set()
        self._lock = threading.Lock()
        self._started = False

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
        threading.Thread(target=self._run, daemon=True).start()
        self.kick()

    def kick(self) -> None:
        for row in self.library.items_needing_posters():
            self.enqueue(dict(row))

    def enqueue(self, item: dict) -> None:
        item_id = item["id"]
        with self._lock:
            if item_id in self._queued:
                return
            self._queued.add(item_id)
        self._queue.put(item)

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            try:
                self._fetch(item)
            except Exception:
                self._retry_or_miss(item)
            finally:
                with self._lock:
                    self._queued.discard(item["id"])
                time.sleep(0.35)

    def _retry_or_miss(self, item: dict) -> None:
        item_id = item["id"]
        tries = item.get("_tries", 0) + 1
        if tries < 2:
            item = dict(item)
            item["_tries"] = tries
            self.enqueue(item)
            return
        self.library.set_poster_state(item_id, 2)

    def _fetch(self, item: dict) -> None:
        dest = poster_path(self.data_dir, item["id"])
        if dest.is_file() and dest.stat().st_size > 400:
            self.library.set_poster_state(item["id"], 1)
            return
        url = self.lookup(item)
        if not url:
            self.library.set_poster_state(item["id"], 2)
            return
        data = download(url)
        kind = sniff_image(data or b"")
        if not data or not kind:
            self.library.set_poster_state(item["id"], 2)
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        temp = dest.with_suffix(".part")
        temp.write_bytes(data)
        temp.replace(dest)
        self.library.set_poster_state(item["id"], 1)

    def lookup(self, item: dict) -> str | None:
        title = item.get("title") or ""
        year = item.get("year")
        kind = item.get("kind") or "movie"
        key = (self.library.setting("tmdb_key", "") or "").strip()
        if key:
            url = tmdb_poster(key, title, year, kind)
            if url:
                return url
        url = wikidata_poster(title, year, kind)
        if url:
            return url
        url = wiki_search_poster(title, year, kind)
        if url:
            return url
        if kind == "series":
            return tvmaze_poster(title)
        return None


def download(url: str) -> bytes | None:
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            ctype = response.headers.get("Content-Type", "")
            if "svg" in ctype:
                return None
            data = response.read(2_500_001)
    except (OSError, urllib.error.URLError, TimeoutError):
        return None
    if len(data) < 500 or len(data) > 2_500_000:
        return None
    return data


def _get_json(url: str) -> dict | None:
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8", "replace"))
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
        return None


def _score_entity(hit: dict, title: str, year: int | None, kind: str) -> int:
    desc = (hit.get("description") or "").casefold()
    label = (hit.get("label") or "").casefold()
    if any(bad in desc for bad in BAD_DESC):
        return -1
    score = 0
    if kind == "movie" and any(word in desc for word in GOOD_MOVIE):
        score += 6
    if kind == "series" and any(word in desc for word in GOOD_SERIES):
        score += 6
    if year and str(year) in desc:
        score += 4
    wanted = title.casefold()
    if wanted and (wanted == label or wanted in label or label in wanted):
        score += 3
    return score


def wikidata_poster(title: str, year: int | None, kind: str) -> str | None:
    # Year in the search string makes Wikidata return nothing. Score with it instead.
    query = title
    best = None
    best_score = 4
    for lang in ("no", "en"):
        params = urllib.parse.urlencode(
            {
                "action": "wbsearchentities",
                "search": query,
                "language": lang,
                "format": "json",
                "type": "item",
                "limit": "6",
            }
        )
        data = _get_json("https://www.wikidata.org/w/api.php?" + params)
        if not data:
            continue
        for hit in data.get("search") or []:
            score = _score_entity(hit, title, year, kind)
            if score > best_score:
                best_score = score
                best = hit
        if best_score >= 9:
            break
    if not best:
        return None
    qid = best.get("id")
    if not qid:
        return None
    page_url = _sitelink_poster(qid)
    if page_url:
        return page_url
    claims = _get_json(
        "https://www.wikidata.org/w/api.php?"
        + urllib.parse.urlencode(
            {"action": "wbgetclaims", "entity": qid, "property": "P18", "format": "json"}
        )
    )
    filename = ""
    try:
        filename = claims["claims"]["P18"][0]["mainsnak"]["datavalue"]["value"]
    except (TypeError, KeyError, IndexError):
        filename = ""
    if filename and not filename.lower().endswith(".svg"):
        url = commons_thumb(filename)
        if url:
            return url
    return None


def _sitelink_poster(qid: str) -> str | None:
    entity = _get_json(
        "https://www.wikidata.org/w/api.php?"
        + urllib.parse.urlencode(
            {
                "action": "wbgetentities",
                "ids": qid,
                "props": "sitelinks",
                "sitefilter": "nowiki|enwiki",
                "format": "json",
            }
        )
    )
    sitelinks = {}
    try:
        sitelinks = entity["entities"][qid]["sitelinks"]
    except (TypeError, KeyError):
        return None
    for site in ("nowiki", "enwiki"):
        page = (sitelinks.get(site) or {}).get("title")
        if not page:
            continue
        url = wiki_page_image("no" if site == "nowiki" else "en", page)
        if url:
            return url
    return None


def commons_thumb(filename: str) -> str | None:
    params = urllib.parse.urlencode(
        {
            "action": "query",
            "titles": "File:" + filename,
            "prop": "imageinfo",
            "iiprop": "url|mime",
            "iiurlwidth": "480",
            "format": "json",
        }
    )
    data = _get_json("https://commons.wikimedia.org/w/api.php?" + params)
    pages = (data or {}).get("query", {}).get("pages", {})
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        if "svg" in (info.get("mime") or ""):
            return None
        return info.get("thumburl") or info.get("url")
    return None


def wiki_page_image(lang: str, title: str) -> str | None:
    params = urllib.parse.urlencode(
        {
            "action": "query",
            "titles": title,
            "prop": "pageimages",
            "piprop": "thumbnail",
            "pithumbsize": "480",
            "pilicense": "any",
            "format": "json",
            "formatversion": "2",
        }
    )
    data = _get_json(f"https://{lang}.wikipedia.org/w/api.php?" + params)
    pages = (data or {}).get("query", {}).get("pages") or []
    if not pages:
        return None
    thumb = pages[0].get("thumbnail") or {}
    source = thumb.get("source") or ""
    if not source or source.lower().split("?")[0].endswith(".svg"):
        return None
    width = thumb.get("width") or 0
    height = thumb.get("height") or 0
    if width and height and height < width:
        return None
    return source


def wiki_search_poster(title: str, year: int | None, kind: str) -> str | None:
    hint = "film" if kind == "movie" else "television series"
    query = f"{title} {year or ''} {hint}".strip()
    for lang in ("no", "en"):
        params = urllib.parse.urlencode(
            {
                "action": "query",
                "generator": "search",
                "gsrsearch": query,
                "gsrlimit": "5",
                "prop": "pageimages|pageterms",
                "piprop": "thumbnail",
                "pithumbsize": "480",
                "pilicense": "any",
                "format": "json",
                "formatversion": "2",
            }
        )
        data = _get_json(f"https://{lang}.wikipedia.org/w/api.php?" + params)
        best = None
        best_score = 0
        for page in (data or {}).get("query", {}).get("pages") or []:
            desc = " ".join((page.get("terms") or {}).get("description") or []).casefold()
            if any(bad in desc for bad in ("disambiguation", "pekerside", "soundtrack", "album", "skuespiller", "actress", "actor", "filmmaker")):
                continue
            thumb = page.get("thumbnail") or {}
            source = thumb.get("source") or ""
            width = thumb.get("width") or 0
            height = thumb.get("height") or 0
            if not source or source.lower().split("?")[0].endswith(".svg"):
                continue
            if width and height and height < width:
                continue
            score = 1
            page_title = (page.get("title") or "").casefold()
            if title.casefold() in page_title:
                score += 4
            if year and str(year) in page_title + " " + desc:
                score += 3
            if kind == "movie" and "film" in desc:
                score += 3
            if kind == "series" and ("series" in desc or "serie" in desc):
                score += 3
            if score > best_score:
                best_score = score
                best = source
        if best and best_score >= 4:
            return best
    return None


def tvmaze_poster(title: str) -> str | None:
    url = "https://api.tvmaze.com/singlesearch/shows?q=" + urllib.parse.quote(title)
    data = _get_json(url)
    if not data:
        return None
    image = data.get("image") or {}
    return image.get("original") or image.get("medium")


def tmdb_poster(key: str, title: str, year: int | None, kind: str) -> str | None:
    branch = "movie" if kind == "movie" else "tv"
    for language in ("no-NO", "en-US"):
        params = {
            "api_key": key,
            "query": title,
            "include_adult": "false",
            "language": language,
        }
        if year and kind == "movie":
            params["year"] = str(year)
        if year and kind == "series":
            params["first_air_date_year"] = str(year)
        data = _get_json(
            f"https://api.themoviedb.org/3/search/{branch}?" + urllib.parse.urlencode(params)
        )
        results = (data or {}).get("results") or []
        for result in results[:3]:
            poster = result.get("poster_path")
            if poster:
                return "https://image.tmdb.org/t/p/w500" + poster
    return None
