"""Local-only web server for Mine filmer. Binds to 127.0.0.1."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import argparse
import json
import os
import secrets
import subprocess
import sys
import threading
import traceback
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app.demo import seed
from app.library import Library
from app.player import VlcPlayer, find_vlc
from app.posters import PosterWorker, poster_path, sniff_image
from app.scan import auto_roots, scan_root
from app.titles import format_duration
from app.trash import TrashError, trash_item

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
ASSETS = ROOT / "assets"
HOST = "127.0.0.1"
DEFAULT_PORT = 47631


def log(data_dir: Path, message: str) -> None:
    try:
        path = Path(data_dir) / "server.log"
        if path.exists() and path.stat().st_size > 200_000:
            path.write_text("", encoding="utf-8")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(message.rstrip() + "\n")
    except OSError:
        pass


class App:
    def __init__(self, data_dir: Path, demo: bool = False, fetch_posters: bool = True):
        self.data_dir = Path(data_dir)
        self.demo = demo
        self.library = Library(self.data_dir)
        if demo:
            seed(self.library)
        token = self.library.setting("token")
        if not token:
            token = secrets.token_hex(16)
            self.library.set_setting("token", token)
        self.token = token
        password = self.library.setting("vlc_password")
        if not password:
            password = secrets.token_hex(8)
            self.library.set_setting("vlc_password", password)
        self.player = VlcPlayer(self.library, password)
        self.posters = PosterWorker(self.library, self.data_dir)
        self.scan = {"running": False, "found": 0, "current": "", "error": ""}
        self._scan_guard = threading.Lock()
        if fetch_posters:
            self.posters.start()
        if not demo:
            self.start_scan()
            threading.Thread(target=self._watch_drives, daemon=True).start()

    def active_roots(self) -> list[str]:
        custom = self.library.roots()
        return custom if custom else auto_roots()

    def start_scan(self) -> bool:
        with self._scan_guard:
            if self.scan["running"]:
                return False
            self.scan["running"] = True
            self.scan["found"] = 0
            self.scan["error"] = ""
            self.scan["current"] = ""
        threading.Thread(target=self._scan, daemon=True).start()
        return True

    def _scan(self) -> None:
        seen: list[str] = []
        roots = self.active_roots()
        try:
            if not roots:
                self.scan["error"] = (
                    "Ingen mapper å lete i. Legg til en mappe under Innstillinger."
                )
            for root in roots:
                self.scan["current"] = root
                if not os.path.exists(root):
                    continue

                def on_dir(path: str) -> None:
                    self.scan["current"] = path

                for found in scan_root(Path(root), on_dir=on_dir):
                    seen.append(self.library.upsert_found(found))
                    self.scan["found"] = len(seen)
            self.library.finish_scan(set(seen), roots)
            self.posters.kick()
        except Exception:
            self.scan["error"] = "Skanningen stoppet. Prøv igjen."
            log(self.data_dir, traceback.format_exc())
        finally:
            self.scan["running"] = False
            self.scan["current"] = ""

    def _watch_drives(self) -> None:
        if os.name != "nt":
            return
        previous = self._drive_set()
        while True:
            threading.Event().wait(25)
            if self.library.roots():
                previous = self._drive_set()
                continue
            current = self._drive_set()
            if current - previous and not self.scan["running"]:
                self.start_scan()
            previous = current

    def _drive_set(self) -> set[str]:
        import ctypes
        import string

        kernel = ctypes.windll.kernel32
        found = set()
        for letter in string.ascii_uppercase:
            drive = f"{letter}:\\"
            if int(kernel.GetDriveTypeW(drive)) in (2, 3):
                found.add(drive)
        return found

    def bootstrap(self) -> dict:
        payload = self.library.summaries(demo=self.demo)
        payload["scan"] = dict(self.scan)
        payload["vlc"] = bool(find_vlc(self.library.setting("vlc_path")))
        payload["demo"] = self.demo
        payload["roots"] = self.library.roots()
        return payload

    def play(self, item_id: str, episode_id: str | None, from_start: bool) -> dict:
        detail = self.library.item_detail(item_id, demo=self.demo)
        if not detail:
            return {"ok": False, "error": "Finner ikke filmen.", "status": 404}
        episode = None
        if episode_id:
            episode = next((ep for ep in detail["episodes"] if ep["id"] == episode_id), None)
            if not episode:
                return {"ok": False, "error": "Finner ikke episoden.", "status": 404}
        if detail["kind"] == "movie" and episode is None:
            files = [ep["path"] for ep in detail["episodes"]]
            saved_path = files[0] if files else ""
            resume = detail["resume"]
        else:
            chosen = episode
            if chosen is None:
                match = detail["resume"].get("episodeId")
                chosen = next((ep for ep in detail["episodes"] if ep["id"] == match), None)
                chosen = chosen or (detail["episodes"][0] if detail["episodes"] else None)
            if not chosen:
                return {"ok": False, "error": "Finner ingen videofil."}
            files = [chosen["path"]]
            saved_path = chosen["path"]
            if episode_id:
                from app.player import resume_point

                point = resume_point(chosen.get("position"), chosen.get("duration"))
                resume = point
            else:
                resume = detail["resume"]
        start = 0 if from_start else int(resume.get("start") or 0)
        if not files or not saved_path:
            return {"ok": False, "error": "Finner ingen videofil."}
        vlc = find_vlc(self.library.setting("vlc_path"))
        if not vlc:
            return {
                "ok": False,
                "code": "vlc-missing",
                "start": start,
                "label": format_duration(start) if start else "",
            }
        if not all(os.path.exists(path) for path in files):
            return {
                "ok": False,
                "code": "offline",
                "start": start,
                "error": "Disken er ikke koblet til.",
            }
        result = self.player.play(files, start, vlc)
        result["start"] = start
        return result

    def reveal(self, path: str) -> dict:
        if not path:
            return {"ok": False, "error": "Mangler sti."}
        if os.name != "nt":
            return {
                "ok": False,
                "error": "Vis i Utforsker virker på Windows. Stien står under tittelen.",
            }
        if not os.path.exists(path):
            return {"ok": False, "error": "Disken er ikke koblet til."}
        subprocess.Popen(["explorer.exe", f"/select,{path}"])
        return {"ok": True}

    def discard(self, item_id: str, episode_id: str | None) -> dict:
        detail = self.library.item_detail(item_id, demo=self.demo)
        if not detail:
            return {"ok": False, "error": "Finner ikke filmen.", "status": 404}
        episode = None
        if episode_id:
            episode = next((ep for ep in detail["episodes"] if ep["id"] == episode_id), None)
            if not episode:
                return {"ok": False, "error": "Finner ikke episoden.", "status": 404}
        exists = os.path.exists(detail["folder"]) or any(
            os.path.exists(ep["path"]) for ep in detail["episodes"]
        )
        if not exists:
            return {
                "ok": False,
                "error": "Finner ikke mappen. Er disken koblet til?",
            }
        try:
            moved = trash_item(detail, episode, self.active_roots())
        except TrashError as exc:
            return {"ok": False, "error": str(exc)}
        if episode and len(detail["episodes"]) > 1:
            self.library.remove_episode(item_id, episode["id"])
        else:
            self.library.forget_item(item_id)
        return {"ok": True, "moved": moved}

    def shortcut(self) -> dict:
        if os.name != "nt":
            return {
                "ok": False,
                "error": "Ikonet på skrivebordet lages på Windows-maskinen.",
            }
        script = ROOT / "installer" / "lag-snarvei.ps1"
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-Dest",
                str(ROOT),
                "-PythonCmd",
                sys.executable,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if completed.returncode != 0:
            log(self.data_dir, completed.stderr or "snarvei feilet")
            return {"ok": False, "error": "Klarte ikke å lage snarveien."}
        return {"ok": True}

    def browse_folder(self) -> dict:
        if os.name != "nt":
            return {
                "ok": False,
                "error": "Bla gjennom virker på Windows. Lim inn stien i feltet.",
            }
        command = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
            "$d.Description = 'Velg mappen med filmer'; "
            "$null = $d.ShowDialog(); "
            "if ($d.SelectedPath) { Write-Output $d.SelectedPath }"
        )
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", command],
            capture_output=True,
            text=True,
            timeout=180,
        )
        lines = [line.strip() for line in (completed.stdout or "").splitlines() if line.strip()]
        if not lines:
            return {"ok": False, "error": "Ingen mappe valgt."}
        return {"ok": True, "path": lines[-1]}


class MineServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, app: App):
        self.app = app
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        return

    def do_GET(self) -> None:
        self._guard(self._get)

    def do_POST(self) -> None:
        self._guard(self._post)

    def _guard(self, method) -> None:
        try:
            if not self._host_ok():
                self._json(403, {"error": "Bare denne PC-en kan åpne Mine filmer."})
                return
            method()
        except Exception:
            log(self.server.app.data_dir, traceback.format_exc())
            try:
                self._json(500, {"error": "Noe gikk galt på denne PC-en."})
            except Exception:
                pass

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0].strip().lower()
        return host in ("127.0.0.1", "localhost")

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        port = self.server.server_address[1]
        allowed = {
            f"http://127.0.0.1:{port}",
            f"http://localhost:{port}",
        }
        return origin in allowed

    def _post_ok(self) -> bool:
        if not self._origin_ok():
            self._json(403, {"error": "Avvist."})
            return False
        if self.headers.get("X-Mine-Token") != self.server.app.token:
            self._json(403, {"error": "Avvist."})
            return False
        return True

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or "0")
        if length > 1_000_000:
            raise ValueError("for stor")
        raw = self.rfile.read(length) if length else b"{}"
        if not raw.strip():
            return {}
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("json")
        return data

    def _json(self, code: int, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _bytes(self, code: int, data: bytes, content_type: str, cache: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(data)

    def _get(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        app = self.server.app
        if path == "/health":
            self._json(200, {"ok": True})
            return
        if path == "/api/bootstrap":
            self._json(200, app.bootstrap())
            return
        if path == "/api/scan":
            self._json(200, dict(app.scan))
            return
        if path == "/api/settings":
            self._json(
                200,
                {
                    "roots": app.library.roots(),
                    "vlcPath": app.library.setting("vlc_path", "") or "",
                    "tmdbKey": app.library.setting("tmdb_key", "") or "",
                    "vlc": bool(find_vlc(app.library.setting("vlc_path"))),
                },
            )
            return
        if path.startswith("/api/item/"):
            item_id = path.split("/")[-1]
            detail = app.library.item_detail(item_id, demo=app.demo)
            if not detail:
                self._json(404, {"error": "Finner ikke filmen."})
                return
            self._json(200, detail)
            return
        if path.startswith("/poster/"):
            self._poster(path.split("/")[-1])
            return
        if path in ("/", "/index.html"):
            html = (WEB / "index.html").read_text(encoding="utf-8")
            html = html.replace("{{TOKEN}}", app.token)
            self._bytes(200, html.encode("utf-8"), "text/html; charset=utf-8", "no-store")
            return
        static = {
            "/styles.css": (WEB / "styles.css", "text/css; charset=utf-8"),
            "/app.js": (WEB / "app.js", "text/javascript; charset=utf-8"),
            "/icon.png": (ASSETS / "icon.png", "image/png"),
            "/favicon.ico": (ASSETS / "icon.ico", "image/x-icon"),
        }
        if path in static:
            file, ctype = static[path]
            if not file.is_file():
                self._json(404, {"error": "Mangler fil."})
                return
            cache = "no-cache" if path.endswith((".css", ".js")) else "public, max-age=86400"
            self._bytes(200, file.read_bytes(), ctype, cache)
            return
        self._json(404, {"error": "Finner ikke siden."})

    def _poster(self, item_id: str) -> None:
        if len(item_id) != 16 or any(ch not in "0123456789abcdef" for ch in item_id):
            self._json(404, {"error": "Ukjent bilde."})
            return
        app = self.server.app
        path = poster_path(app.data_dir, item_id)
        if path.is_file():
            data = path.read_bytes()
            kind = sniff_image(data)
            if kind:
                self._bytes(200, data, kind, "public, max-age=86400")
                return
        detail = app.library.item_detail(item_id, demo=app.demo)
        title = detail["title"] if detail else "Film"
        svg = placeholder_svg(title, item_id).encode("utf-8")
        self._bytes(200, svg, "image/svg+xml; charset=utf-8", "no-store")

    def _post(self) -> None:
        if not self._post_ok():
            return
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        app = self.server.app
        try:
            body = self._body()
        except (ValueError, json.JSONDecodeError):
            self._json(400, {"error": "Ugyldig forespørsel."})
            return
        if path == "/api/play":
            result = app.play(
                str(body.get("itemId") or ""),
                body.get("episodeId") or None,
                bool(body.get("fromStart")),
            )
            status = int(result.pop("status", 200 if result.get("ok") or result.get("code") else 200))
            self._json(status, result)
            return
        if path == "/api/trash":
            result = app.discard(str(body.get("itemId") or ""), body.get("episodeId") or None)
            self._json(int(result.pop("status", 200)), result)
            return
        if path == "/api/reveal":
            detail = app.library.item_detail(str(body.get("itemId") or ""), demo=app.demo)
            if not detail:
                self._json(404, {"error": "Finner ikke filmen."})
                return
            target = detail["folder"]
            if body.get("episodeId"):
                episode = next(
                    (ep for ep in detail["episodes"] if ep["id"] == body["episodeId"]),
                    None,
                )
                if episode:
                    target = episode["path"]
            self._json(200, app.reveal(target))
            return
        if path == "/api/scan":
            started = app.start_scan()
            self._json(200, {"ok": True, "started": started, **app.scan})
            return
        if path == "/api/progress":
            detail = app.library.item_detail(str(body.get("itemId") or ""), demo=app.demo)
            if not detail:
                self._json(404, {"error": "Finner ikke filmen."})
                return
            episodes = detail["episodes"]
            if body.get("episodeId"):
                episodes = [ep for ep in episodes if ep["id"] == body["episodeId"]]
            finished = bool(body.get("finished"))
            for ep in episodes:
                app.library.mark_finished(ep["path"], finished)
            self._json(200, {"ok": True})
            return
        if path == "/api/categories":
            try:
                created = app.library.add_category(str(body.get("name") or ""))
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
                return
            self._json(200, created)
            return
        if path == "/api/categories/rename":
            try:
                app.library.rename_category(str(body.get("id") or ""), str(body.get("name") or ""))
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
                return
            except KeyError:
                self._json(404, {"error": "Finner ikke kategorien."})
                return
            self._json(200, {"ok": True})
            return
        if path == "/api/categories/delete":
            app.library.delete_category(str(body.get("id") or ""))
            self._json(200, {"ok": True})
            return
        if path == "/api/categories/items":
            app.library.set_membership(
                str(body.get("categoryId") or ""),
                str(body.get("itemId") or ""),
                bool(body.get("include")),
            )
            self._json(200, {"ok": True})
            return
        if path == "/api/settings":
            if "roots" in body and isinstance(body["roots"], list):
                app.library.set_roots([str(item) for item in body["roots"]])
            if "vlcPath" in body:
                app.library.set_setting("vlc_path", str(body.get("vlcPath") or "").strip())
            if "tmdbKey" in body:
                app.library.set_setting("tmdb_key", str(body.get("tmdbKey") or "").strip())
            self._json(200, {"ok": True})
            return
        if path == "/api/browse-folder":
            self._json(200, app.browse_folder())
            return
        if path == "/api/shortcut":
            self._json(200, app.shortcut())
            return
        self._json(404, {"error": "Ukjent handling."})


def placeholder_svg(title: str, item_id: str) -> str:
    palette = ("#3a2a16", "#1d2c33", "#2c1e24", "#1c2c22", "#332816")
    color = palette[int(item_id[:2], 16) % len(palette)]
    safe = (
        title.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "")
    )
    words = safe.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = (current + " " + word).strip()
        if len(trial) > 14 and current:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    lines = lines[:4] or ["Film"]
    tspans = []
    start = 250 - (len(lines) - 1) * 22
    for index, line in enumerate(lines):
        tspans.append(
            f'<tspan x="32" y="{start + index * 46}">{line}</tspan>'
        )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="600" viewBox="0 0 400 600">'
        f'<rect width="400" height="600" fill="{color}"/>'
        '<rect x="24" y="24" width="352" height="552" rx="18" fill="none" stroke="#e8b86d" stroke-width="3"/>'
        '<text fill="#f7f3ea" font-family="Georgia, serif" font-size="36">'
        + "".join(tspans)
        + "</text></svg>"
    )


def health_ok(port: int) -> bool:
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
            return response.status == 200
    except OSError:
        return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mine filmer")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--data", default="")
    parser.add_argument("--open", action="store_true")
    parser.add_argument("--no-posters", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.data:
        data = Path(args.data)
    elif args.demo:
        data = ROOT / "data-demo"
    else:
        data = Path(os.environ.get("MINEFILMER_DATA", ROOT / "data"))
    try:
        app = App(data, demo=args.demo, fetch_posters=not args.no_posters)
        server = MineServer((HOST, args.port), app)
    except OSError:
        if health_ok(args.port):
            if args.open:
                webbrowser.open(f"http://{HOST}:{args.port}/")
            print(f"Mine filmer kjører allerede på http://{HOST}:{args.port}/")
            return 0
        raise
    url = f"http://{HOST}:{server.server_address[1]}/"
    print(f"Mine filmer kjører på {url}")
    if args.open:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStoppet.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
