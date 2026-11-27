"""Open a file in VLC and remember how far it got."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
import urllib.request
from base64 import b64encode
from pathlib import Path

from app.titles import format_duration

VLC_PORT = 47632
_TIME = re.compile(r"<time>(-?\d+(?:\.\d+)?)</time>")
_LENGTH = re.compile(r"<length>(-?\d+(?:\.\d+)?)</length>")


def resume_point(position: float | None, duration: float | None) -> dict:
    position = float(position or 0)
    duration = float(duration or 0)
    if position < 30:
        mode = "start"
        start = 0
    elif duration and position >= duration * 0.9:
        mode = "finished"
        start = 0
    else:
        mode = "resume"
        start = max(0, int(position) - 10)
    return {
        "mode": mode,
        "position": position,
        "duration": duration,
        "start": start,
    }


def decide_resume(kind: str, entries: list[dict], progress: dict[str, dict]) -> dict:
    """Pick where Play should start.

    entries are sorted episodes (or movie parts). progress is keyed by normpath.
    """
    empty = {
        "mode": "start", "position": 0, "duration": 0, "start": 0,
        "episodeId": None, "path": None, "updated": 0, "episodeTitle": "",
        "label": "Spill av",
    }
    if not entries:
        return empty

    def prog_for(entry: dict) -> dict:
        key = os.path.normcase(os.path.normpath(entry["path"]))
        return progress.get(key) or {}

    def pack(entry: dict, point: dict, updated: float, mode: str | None = None) -> dict:
        chosen = mode or point["mode"]
        title = entry.get("title") or ""
        if chosen == "resume":
            label = "Fortsett fra " + format_duration(point["position"])
        elif chosen == "next":
            label = "Neste: " + (title or "neste episode")
        elif chosen == "finished":
            label = "Sett"
        else:
            label = "Spill av"
        return {
            "mode": chosen,
            "position": point["position"],
            "duration": point["duration"],
            "start": 0 if chosen in ("next", "finished", "start") else point["start"],
            "episodeId": entry.get("id"),
            "path": entry.get("path"),
            "updated": updated,
            "episodeTitle": title,
            "label": label,
        }

    if kind == "movie":
        entry = entries[0]
        saved = prog_for(entry)
        point = resume_point(saved.get("position"), saved.get("duration"))
        return pack(entry, point, float(saved.get("updated") or 0))

    decorated = [(entry, prog_for(entry)) for entry in entries]
    unfinished = []
    for entry, saved in decorated:
        if not saved:
            continue
        point = resume_point(saved.get("position"), saved.get("duration"))
        if point["mode"] == "resume":
            unfinished.append((entry, saved, point))
    if unfinished:
        entry, saved, point = max(unfinished, key=lambda row: float(row[1].get("updated") or 0))
        return pack(entry, point, float(saved.get("updated") or 0))

    finished_at = []
    for index, (entry, saved) in enumerate(decorated):
        if not saved:
            continue
        point = resume_point(saved.get("position"), saved.get("duration"))
        if point["mode"] == "finished" or saved.get("finished"):
            finished_at.append(index)
    if finished_at:
        last = max(finished_at)
        updated = float(decorated[last][1].get("updated") or 0)
        if last + 1 < len(entries):
            nxt = entries[last + 1]
            point = resume_point(0, 0)
            return pack(nxt, point, updated, mode="next")
        return pack(entries[last], resume_point(1, 1), updated, mode="finished")

    return pack(entries[0], resume_point(0, 0), 0, mode="start")


def vlc_command(vlc: str, files: list[str], start: int, password: str, port: int = VLC_PORT) -> list[str]:
    return [
        vlc,
        *files,
        f"--start-time={int(start)}",
        "--extraintf=http",
        "--http-host=127.0.0.1",
        "--http-port=" + str(port),
        "--http-password=" + password,
    ]


def find_vlc(override: str | None = None) -> str | None:
    if override and Path(override).is_file():
        return override
    found = shutil.which("vlc")
    if found:
        return found
    for candidate in (
        r"C:\Program Files\VideoLAN\VLC\vlc.exe",
        r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
    ):
        if Path(candidate).is_file():
            return candidate
    return None


class VlcPlayer:
    def __init__(self, library, password: str):
        self.library = library
        self.password = password
        self._lock = threading.Lock()

    def play(self, files: list[str], start: int, vlc_path: str | None) -> dict:
        vlc = find_vlc(vlc_path)
        label = format_duration(start) if start else ""
        if not vlc:
            return {
                "ok": False,
                "code": "vlc-missing",
                "start": int(start),
                "label": label,
            }
        if not files:
            return {"ok": False, "code": "no-file", "error": "Finner ingen videofil."}
        missing = [path for path in files if not os.path.exists(path)]
        if missing:
            return {
                "ok": False,
                "code": "offline",
                "error": "Disken er ikke koblet til.",
            }
        command = vlc_command(vlc, files, start, self.password)
        kwargs = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        proc = subprocess.Popen(command, **kwargs)
        threading.Thread(
            target=self._watch, args=(proc, files[0]), daemon=True
        ).start()
        return {"ok": True, "start": int(start), "label": label}

    def _watch(self, proc: subprocess.Popen, path: str) -> None:
        while proc.poll() is None:
            position, duration = self.read_status()
            if position is not None and position >= 0:
                self.library.set_progress(path, position, duration or 0)
            time.sleep(5)
        position, duration = self.read_status()
        if position is not None and position >= 0:
            self.library.set_progress(path, position, duration or 0)

    def read_status(self) -> tuple[float | None, float | None]:
        url = f"http://127.0.0.1:{VLC_PORT}/requests/status.xml"
        request = urllib.request.Request(url)
        token = b64encode(f":{self.password}".encode("utf-8")).decode("ascii")
        request.add_header("Authorization", "Basic " + token)
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                text = response.read().decode("utf-8", "replace")
        except (OSError, ValueError):
            return None, None
        time_match = _TIME.search(text)
        length_match = _LENGTH.search(text)
        position = float(time_match.group(1)) if time_match else None
        duration = float(length_match.group(1)) if length_match else None
        return position, duration
