"""SQLite library: titles, episodes, progress, categories, settings."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from pathlib import Path

from app.player import decide_resume
from app.scan import Found

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  container TEXT NOT NULL,
  title TEXT NOT NULL,
  sort_title TEXT NOT NULL,
  year INTEGER,
  folder TEXT NOT NULL,
  size INTEGER NOT NULL DEFAULT 0,
  mtime REAL NOT NULL DEFAULT 0,
  missing INTEGER NOT NULL DEFAULT 0,
  subtitle_count INTEGER NOT NULL DEFAULT 0,
  poster INTEGER NOT NULL DEFAULT 0,
  overview TEXT
);
CREATE TABLE IF NOT EXISTS episodes (
  id TEXT PRIMARY KEY,
  item_id TEXT NOT NULL,
  season INTEGER,
  episode INTEGER,
  part INTEGER,
  title TEXT,
  path TEXT NOT NULL,
  size INTEGER NOT NULL DEFAULT 0,
  ord INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS progress (
  path_key TEXT PRIMARY KEY,
  position REAL NOT NULL,
  duration REAL NOT NULL,
  finished INTEGER NOT NULL DEFAULT 0,
  updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS categories (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS category_items (
  category_id TEXT NOT NULL,
  item_id TEXT NOT NULL,
  PRIMARY KEY (category_id, item_id)
);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""


def make_id(path: str) -> str:
    key = os.path.normcase(os.path.normpath(path))
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def path_key(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def path_is_under(path: str, root: str) -> bool:
    path_n = path_key(path)
    root_n = path_key(root)
    if path_n == root_n:
        return True
    sep = os.sep
    if not root_n.endswith(sep):
        root_n = root_n + sep
    return path_n.startswith(root_n)


def sort_title(title: str) -> str:
    folded = title.casefold()
    for prefix in ("the ", "a ", "an "):
        if folded.startswith(prefix):
            return folded[len(prefix):]
    return folded


class Library:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "library.sqlite"
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def setting(self, key: str, default: str | None = None) -> str | None:
        with self._lock:
            row = self._db.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            self._db.commit()

    def roots(self) -> list[str]:
        raw = self.setting("roots", "")
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if isinstance(data, list):
            return [str(item) for item in data if str(item).strip()]
        return []

    def set_roots(self, roots: list[str]) -> None:
        clean = []
        seen = set()
        for root in roots:
            root = root.strip()
            if not root:
                continue
            key = path_key(root)
            if key in seen:
                continue
            seen.add(key)
            clean.append(root)
        self.set_setting("roots", json.dumps(clean, ensure_ascii=False))

    def upsert_found(self, found: Found) -> str:
        item_id = make_id(found.id_path)
        size = sum(video.size for video in found.videos)
        mtime = max((video.mtime for video in found.videos), default=0)
        with self._lock:
            self._db.execute(
                """
                INSERT INTO items (
                  id, kind, container, title, sort_title, year, folder,
                  size, mtime, missing, subtitle_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                ON CONFLICT(id) DO UPDATE SET
                  kind = excluded.kind,
                  container = excluded.container,
                  title = excluded.title,
                  sort_title = excluded.sort_title,
                  year = excluded.year,
                  folder = excluded.folder,
                  size = excluded.size,
                  mtime = excluded.mtime,
                  missing = 0,
                  subtitle_count = excluded.subtitle_count
                """,
                (
                    item_id, found.kind, found.container, found.title,
                    sort_title(found.title), found.year, found.folder,
                    size, mtime, found.subtitle_count,
                ),
            )
            self._db.execute("DELETE FROM episodes WHERE item_id = ?", (item_id,))
            for order, video in enumerate(found.videos):
                label = _episode_title(found, video)
                self._db.execute(
                    """
                    INSERT INTO episodes (
                      id, item_id, season, episode, part, title, path, size, ord
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        make_id(str(video.path)), item_id, video.season, video.episode,
                        video.part, label, str(video.path), video.size, order,
                    ),
                )
            self._db.commit()
        return item_id

    def finish_scan(self, seen_ids: set[str], roots: list[str]) -> None:
        with self._lock:
            rows = self._db.execute("SELECT id, folder FROM items").fetchall()
            for row in rows:
                if row["id"] in seen_ids:
                    continue
                covered = [root for root in roots if path_is_under(row["folder"], root)]
                if not covered:
                    continue
                if any(os.path.exists(root) for root in covered):
                    self._db.execute(
                        "UPDATE items SET missing = 1 WHERE id = ?", (row["id"],)
                    )
            self._db.commit()

    def set_poster_state(self, item_id: str, state: int) -> None:
        with self._lock:
            self._db.execute(
                "UPDATE items SET poster = ? WHERE id = ?", (state, item_id)
            )
            self._db.commit()

    def items_needing_posters(self) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(
                "SELECT id, title, year, kind FROM items WHERE poster = 0 AND missing = 0"
            ).fetchall()

    def set_progress(self, path: str, position: float, duration: float) -> None:
        finished = 1 if duration and position >= duration * 0.9 else 0
        now = time.time()
        with self._lock:
            self._db.execute(
                """
                INSERT INTO progress(path_key, position, duration, finished, updated)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(path_key) DO UPDATE SET
                  position = excluded.position,
                  duration = excluded.duration,
                  finished = excluded.finished,
                  updated = excluded.updated
                """,
                (path_key(path), float(position), float(duration or 0), finished, now),
            )
            self._db.commit()

    def mark_finished(self, path: str, finished: bool) -> None:
        now = time.time()
        if finished:
            self._db_exec_progress(path, 100, 100, 1, now)
        else:
            with self._lock:
                self._db.execute(
                    "DELETE FROM progress WHERE path_key = ?", (path_key(path),)
                )
                self._db.commit()

    def _db_exec_progress(self, path, position, duration, finished, now) -> None:
        with self._lock:
            self._db.execute(
                """
                INSERT INTO progress(path_key, position, duration, finished, updated)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(path_key) DO UPDATE SET
                  position = excluded.position,
                  duration = excluded.duration,
                  finished = excluded.finished,
                  updated = excluded.updated
                """,
                (path_key(path), position, duration, finished, now),
            )
            self._db.commit()

    def progress_map(self) -> dict[str, dict]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM progress").fetchall()
        return {
            row["path_key"]: {
                "position": row["position"],
                "duration": row["duration"],
                "finished": bool(row["finished"]),
                "updated": row["updated"],
            }
            for row in rows
        }

    def categories(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id, name, created FROM categories ORDER BY name COLLATE NOCASE"
            ).fetchall()
            links = self._db.execute(
                "SELECT category_id, item_id FROM category_items"
            ).fetchall()
        by_cat: dict[str, list[str]] = {}
        for link in links:
            by_cat.setdefault(link["category_id"], []).append(link["item_id"])
        return [
            {
                "id": row["id"],
                "name": row["name"],
                "created": row["created"],
                "items": by_cat.get(row["id"], []),
            }
            for row in rows
        ]

    def add_category(self, name: str) -> dict:
        name = " ".join(name.split())
        if not name:
            raise ValueError("Kategorien trenger et navn.")
        if len(name) > 40:
            raise ValueError("Navnet er for langt.")
        cat_id = hashlib.sha1(
            f"{name.casefold()}|{time.time()}".encode("utf-8")
        ).hexdigest()[:12]
        now = time.time()
        with self._lock:
            self._db.execute(
                "INSERT INTO categories(id, name, created) VALUES (?, ?, ?)",
                (cat_id, name, now),
            )
            self._db.commit()
        return {"id": cat_id, "name": name, "created": now, "items": []}

    def rename_category(self, cat_id: str, name: str) -> None:
        name = " ".join(name.split())
        if not name:
            raise ValueError("Kategorien trenger et navn.")
        with self._lock:
            cur = self._db.execute(
                "UPDATE categories SET name = ? WHERE id = ?", (name, cat_id)
            )
            self._db.commit()
        if cur.rowcount == 0:
            raise KeyError(cat_id)

    def delete_category(self, cat_id: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM category_items WHERE category_id = ?", (cat_id,))
            self._db.execute("DELETE FROM categories WHERE id = ?", (cat_id,))
            self._db.commit()

    def set_membership(self, cat_id: str, item_id: str, include: bool) -> None:
        with self._lock:
            if include:
                self._db.execute(
                    "INSERT OR IGNORE INTO category_items(category_id, item_id) VALUES (?, ?)",
                    (cat_id, item_id),
                )
            else:
                self._db.execute(
                    "DELETE FROM category_items WHERE category_id = ? AND item_id = ?",
                    (cat_id, item_id),
                )
            self._db.commit()

    def _episodes(self, item_id: str) -> list[dict]:
        rows = self._db.execute(
            """
            SELECT id, season, episode, part, title, path, size
            FROM episodes WHERE item_id = ? ORDER BY ord
            """,
            (item_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def _online(self, row, demo: bool) -> bool:
        if row["missing"]:
            return False
        if demo:
            return True
        return os.path.exists(row["folder"])

    def summaries(self, demo: bool = False) -> dict:
        progress = self.progress_map()
        with self._lock:
            items = self._db.execute(
                "SELECT * FROM items WHERE missing = 0 ORDER BY sort_title"
            ).fetchall()
            episodes = self._db.execute(
                "SELECT * FROM episodes ORDER BY ord"
            ).fetchall()
            links = self._db.execute(
                "SELECT category_id, item_id FROM category_items"
            ).fetchall()
        by_item: dict[str, list[dict]] = {}
        for ep in episodes:
            by_item.setdefault(ep["item_id"], []).append(dict(ep))
        cats_for: dict[str, list[str]] = {}
        for link in links:
            cats_for.setdefault(link["item_id"], []).append(link["category_id"])
        payload = []
        for row in items:
            eps = by_item.get(row["id"], [])
            resume = decide_resume(row["kind"], eps, progress)
            payload.append(
                {
                    "id": row["id"],
                    "kind": row["kind"],
                    "container": row["container"],
                    "title": row["title"],
                    "year": row["year"],
                    "folder": row["folder"],
                    "size": row["size"],
                    "mtime": row["mtime"],
                    "online": self._online(row, demo),
                    "poster": row["poster"],
                    "subtitleCount": row["subtitle_count"],
                    "episodeCount": len(eps),
                    "categories": cats_for.get(row["id"], []),
                    "resume": resume,
                }
            )
        return {"items": payload, "categories": self.categories()}

    def item_detail(self, item_id: str, demo: bool = False) -> dict | None:
        progress = self.progress_map()
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM items WHERE id = ?", (item_id,)
            ).fetchone()
            if not row:
                return None
            episodes = self._episodes(item_id)
        detailed = []
        for ep in episodes:
            saved = progress.get(path_key(ep["path"])) or {}
            detailed.append(
                {
                    **ep,
                    "position": saved.get("position") or 0,
                    "duration": saved.get("duration") or 0,
                    "finished": bool(saved.get("finished")),
                    "online": True if demo else os.path.exists(ep["path"]),
                }
            )
        resume = decide_resume(row["kind"], episodes, progress)
        return {
            "id": row["id"],
            "kind": row["kind"],
            "container": row["container"],
            "title": row["title"],
            "year": row["year"],
            "folder": row["folder"],
            "size": row["size"],
            "online": self._online(row, demo),
            "poster": row["poster"],
            "subtitleCount": row["subtitle_count"],
            "missing": bool(row["missing"]),
            "categories": [
                cat["id"]
                for cat in self.categories()
                if row["id"] in cat["items"]
            ],
            "episodes": detailed,
            "resume": resume,
        }

    def episode(self, item_id: str, episode_id: str) -> dict | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM episodes WHERE id = ? AND item_id = ?",
                (episode_id, item_id),
            ).fetchone()
        return dict(row) if row else None

    def remove_episode(self, item_id: str, episode_id: str) -> None:
        with self._lock:
            row = self._db.execute(
                "SELECT path FROM episodes WHERE id = ? AND item_id = ?",
                (episode_id, item_id),
            ).fetchone()
            if row:
                self._db.execute(
                    "DELETE FROM progress WHERE path_key = ?", (path_key(row["path"]),)
                )
                self._db.execute("DELETE FROM episodes WHERE id = ?", (episode_id,))
            left = self._db.execute(
                "SELECT COUNT(*) AS n FROM episodes WHERE item_id = ?", (item_id,)
            ).fetchone()["n"]
            if left == 0:
                self._db.execute(
                    "DELETE FROM category_items WHERE item_id = ?", (item_id,)
                )
                self._db.execute("DELETE FROM items WHERE id = ?", (item_id,))
            self._db.commit()

    def forget_item(self, item_id: str) -> None:
        with self._lock:
            paths = self._db.execute(
                "SELECT path FROM episodes WHERE item_id = ?", (item_id,)
            ).fetchall()
            for row in paths:
                self._db.execute(
                    "DELETE FROM progress WHERE path_key = ?", (path_key(row["path"]),)
                )
            self._db.execute("DELETE FROM episodes WHERE item_id = ?", (item_id,))
            self._db.execute("DELETE FROM category_items WHERE item_id = ?", (item_id,))
            self._db.execute("DELETE FROM items WHERE id = ?", (item_id,))
            self._db.commit()


def _episode_title(found: Found, video) -> str:
    if found.kind == "movie":
        if video.part:
            return f"Del {video.part}"
        return found.title
    if video.episode:
        if video.season:
            return f"Sesong {video.season}, episode {video.episode}"
        return f"Episode {video.episode}"
    cleaned, _year = clean_title_safe(video.stem)
    return cleaned or video.stem


def clean_title_safe(stem: str):
    from app.titles import clean_title
    return clean_title(stem)
