"""Behaviour tests for scanning, resume, trash safety, and the local API."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from app.library import Library
from app.player import decide_resume, resume_point, vlc_command
from app.scan import scan_root
from app.server import App, MineServer
from app.titles import clean_title, format_duration, parse_episode
from app.trash import TrashError, assert_safe, trash_item


def write(path: Path, size: int = 64) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


class TitleTests(unittest.TestCase):
    def test_release_name_becomes_a_title(self) -> None:
        title, year = clean_title("Titanic.1997.1080p.BluRay.x264")
        self.assertEqual(title, "Titanic")
        self.assertEqual(year, 1997)

    def test_norwegian_title_is_kept(self) -> None:
        title, year = clean_title("Flåklypa Grand Prix")
        self.assertEqual(title, "Flåklypa Grand Prix")
        self.assertIsNone(year)

    def test_episode_pattern(self) -> None:
        self.assertEqual(parse_episode("Breaking.Bad.S01E02.mkv"), (1, 2))
        self.assertEqual(parse_episode("Show 1x03"), (1, 3))

    def test_one_hour_reads_as_one_hour(self) -> None:
        self.assertEqual(format_duration(3600), "1 t")
        self.assertEqual(format_duration(3720), "1 t 2 min")


class ResumeTests(unittest.TestCase):
    def test_one_hour_rewinds_ten_seconds(self) -> None:
        point = resume_point(3600, 7200)
        self.assertEqual(point["mode"], "resume")
        self.assertEqual(point["start"], 3590)

    def test_finished_starts_over(self) -> None:
        point = resume_point(7000, 7200)
        self.assertEqual(point["mode"], "finished")
        self.assertEqual(point["start"], 0)

    def test_series_continues_unfinished_episode(self) -> None:
        entries = [
            {"id": "e1", "path": r"D:\Show\a.mkv", "title": "Sesong 1, episode 1"},
            {"id": "e2", "path": r"D:\Show\b.mkv", "title": "Sesong 1, episode 2"},
        ]
        progress = {
            os.path.normcase(os.path.normpath(entries[0]["path"])): {
                "position": 2700, "duration": 2700, "finished": True, "updated": 1,
            }
        }
        chosen = decide_resume("series", entries, progress)
        self.assertEqual(chosen["mode"], "next")
        self.assertEqual(chosen["episodeId"], "e2")

    def test_vlc_command_includes_start_time(self) -> None:
        command = vlc_command("vlc.exe", [r"D:\Film\a.mkv"], 3590, "secret")
        self.assertIn("--start-time=3590", command)
        self.assertIn("--extraintf=http", command)
        self.assertNotIn("--intf=dummy", command)


class ScanTests(unittest.TestCase):
    def test_movie_folder_series_and_loose_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            movie = root / "Titanic 1997"
            write(movie / "Titanic.1997.1080p.BluRay.mkv")
            write(movie / "Titanic.nb.srt", 8)
            write(movie / "sample.mkv", 8)
            show = root / "Breaking Bad" / "Season 1"
            write(show / "Breaking.Bad.S01E01.mkv")
            write(show / "Breaking.Bad.S01E02.mkv")
            loose = root / "Filmer"
            write(loose / "One.mkv")
            write(loose / "Two.mkv")
            parts = root / "Inception"
            write(parts / "Inception.cd1.mkv")
            write(parts / "Inception.cd2.mkv")
            found = {item.title: item for item in scan_root(root)}
            self.assertEqual(found["Titanic"].kind, "movie")
            self.assertEqual(found["Titanic"].year, 1997)
            self.assertEqual(found["Titanic"].container, "folder")
            self.assertEqual(len(found["Titanic"].videos), 1)
            self.assertGreaterEqual(found["Titanic"].subtitle_count, 1)
            self.assertEqual(found["Breaking Bad"].kind, "series")
            self.assertEqual(len(found["Breaking Bad"].videos), 2)
            self.assertEqual(found["Inception"].kind, "movie")
            self.assertEqual(len(found["Inception"].videos), 2)
            self.assertIn("One", found)
            self.assertEqual(found["One"].container, "file")
            self.assertNotIn("sample", {item.title.casefold() for item in found.values()})

    def test_norwegian_season_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            show = root / "Beforeigners" / "Sesong 1"
            write(show / "01.mkv")
            write(show / "02.mkv")
            found = scan_root(root)
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0].kind, "series")
            self.assertEqual(found[0].title, "Beforeigners")
            numbers = [video.episode for video in found[0].videos]
            self.assertEqual(numbers, [1, 2])


class TrashTests(unittest.TestCase):
    def test_refuses_a_drive_root(self) -> None:
        with self.assertRaises(TrashError):
            assert_safe(Path(os.path.abspath(os.sep)), [])

    def test_moves_a_movie_folder_when_asked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trash = root / "trash"
            movie = root / "library" / "Titanic"
            write(movie / "Titanic.mkv")
            (movie / "Titanic.srt").write_text("1", encoding="utf-8")
            os.environ["MINEFILMER_TRASH_DIR"] = str(trash)
            try:
                moved = trash_item(
                    {
                        "container": "folder",
                        "folder": str(movie),
                        "episodes": [{"id": "1", "path": str(movie / "Titanic.mkv")}],
                    },
                    None,
                    [str(root / "library")],
                )
            finally:
                os.environ.pop("MINEFILMER_TRASH_DIR", None)
            self.assertFalse(movie.exists())
            self.assertTrue(moved)
            self.assertTrue(any(trash.rglob("Titanic.mkv")))

    def test_refuses_to_trash_the_scan_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(TrashError):
                trash_item(
                    {"container": "folder", "folder": str(root), "episodes": []},
                    None,
                    [str(root)],
                )


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.app = App(Path(self.tmp.name), demo=True, fetch_posters=False)
        self.server = MineServer(("127.0.0.1", 0), self.app)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.app.library.close()
        self.tmp.cleanup()

    def get(self, path: str) -> tuple[int, bytes]:
        with urllib.request.urlopen(self.base + path, timeout=5) as response:
            return response.status, response.read()

    def post(self, path: str, payload: dict, token: str | None) -> tuple[int, dict]:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(self.base + path, data=data, method="POST")
        request.add_header("Content-Type", "application/json")
        if token:
            request.add_header("X-Mine-Token", token)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_page_is_norwegian_and_remembers_one_hour(self) -> None:
        status, body = self.get("/")
        self.assertEqual(status, 200)
        text = body.decode("utf-8")
        self.assertIn("Mine filmer", text)
        self.assertIn(self.app.token, text)
        status, raw = self.get("/api/bootstrap")
        data = json.loads(raw.decode("utf-8"))
        inception = next(item for item in data["items"] if item["title"] == "Inception")
        self.assertEqual(inception["resume"]["mode"], "resume")
        self.assertEqual(inception["resume"]["start"], 3590)
        self.assertIn("1 t", inception["resume"]["label"])
        self.assertTrue(inception["folder"].endswith("Inception (2010)"))
        names = [cat["name"] for cat in data["categories"]]
        self.assertIn("Norske filmer", names)

    def test_trash_and_category_need_the_page_token(self) -> None:
        import urllib.error

        code, _payload = self.post("/api/categories", {"name": "Krim"}, None)
        self.assertEqual(code, 403)
        code, created = self.post("/api/categories", {"name": "Krim"}, self.app.token)
        self.assertEqual(code, 200)
        self.assertEqual(created["name"], "Krim")
        status, raw = self.get("/api/bootstrap")
        data = json.loads(raw.decode("utf-8"))
        item = data["items"][0]
        code, result = self.post(
            "/api/play",
            {"itemId": item["id"]},
            self.app.token,
        )
        self.assertEqual(code, 200)
        self.assertFalse(result["ok"])
        self.assertIn(result["code"], ("vlc-missing", "offline"))


class LibraryTests(unittest.TestCase):
    def test_category_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            library = Library(Path(tmp))
            from app.scan import Found, Video

            video = Video(Path(tmp) / "A.mkv", "A.mkv", "A", 10, 1)
            library.upsert_found(
                Found("x", "movie", "file", "Alpha", 1999, str(Path(tmp)), [video], 0)
            )
            item_id = library.summaries()["items"][0]["id"]
            cat = library.add_category("Norske filmer")
            library.set_membership(cat["id"], item_id, True)
            again = library.summaries()
            self.assertEqual(again["items"][0]["categories"], [cat["id"]])
            library.set_membership(cat["id"], item_id, False)
            self.assertEqual(library.summaries()["items"][0]["categories"], [])


if __name__ == "__main__":
    unittest.main()
