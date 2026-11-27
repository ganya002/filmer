# HANDOFF — Mine filmer

**Status: implemented and tested.** `python3 -m unittest discover -s tests` passes (titles, scan grouping, one-hour resume at start-time 3590, trash safety, token-protected API). The UI was clicked through in a browser: search, filters, category, detail path, trash confirm/cancel, VLC-missing dialog, context menu, settings.

Read this file first if you are an agent picking up the work. Also read `STATUS.json` and `README.md`. Do not restart from scratch. If you change behaviour, update the matching test.

Poster sources are **not** iTunes (that API returned nothing from this network). Order is optional TMDB, then Wikidata/Wikipedia page images, then a Wikipedia search, then TVMaze for series. See `app/posters.py`.

Windows auto-scan does **not** walk all of `C:\`. It uses the user's media folders (Videos, Downloads, Desktop, Documents, and the Norwegian names) plus `C:\Filmer` and every other fixed or removable drive. Whole-disk `C:\` is too slow on the target laptop.

The person who asked is Gabriel. The app is for his step-dad: about 55, old Windows 10 laptop, YouTube takes ~30 seconds, tiny text today, movies and series spread across the laptop and external drives, often with no posters. The whole UI must be Norwegian (bokmål).

If work stopped mid-line, trust the files that exist on disk over this narrative, then continue from `STATUS.json` → `next_step`. Do not restart from scratch if modules already match this design.

## Product (do not drop these)

1. Local website he opens from a **desktop icon** named **Mine filmer**. No typing localhost.
2. Lists movies and series on the internal disk and plugged-in drives.
3. Big readable text. Simple. Sorted. Search and filters.
4. Posters (and banners when a source has them). Cached on disk after first fetch.
5. Each title shows the **exact folder path**, with a button that opens that place in Windows Explorer.
6. Play opens **VLC only**. Never an in-page `<video>` player.
7. If he has watched 1 hour, the next open of the site resumes VLC at that position (`--start-time`).
8. He can create categories and add movies/series to them.
9. He can move the movie folder (video + subtitles) to the Windows recycle bin, with a large confirm step.
10. Right-click context menu on a title, plus a visible **Mer** button with the same actions (he may not right-click).
11. Setup is one double-click of `Installer.bat`. It copies the app, gets Python if needed, creates the desktop shortcut, starts the site.
12. Light on CPU/GPU/RAM. No Electron, no React, no Next.js, no backdrop-filter, no webfonts.
13. Bind **127.0.0.1 only**. Do not publish this app to the public internet. It reads disks and deletes files.

## Stack (decided, do not relitigate)

- Python 3.9+ **stdlib only** (http.server, sqlite3, ctypes, urllib). The Windows embeddable zip has no pip by default.
- Frontend: `web/index.html`, `web/styles.css`, `web/app.js`. No build step.
- Data: `data/library.sqlite` next to the app (gitignored).
- Port: **47631**. VLC http interface: **47632**.
- Install dir on his PC: `%LOCALAPPDATA%\MineFilmer`. Re-running the installer updates code and **keeps** `data\`.

## Why not a hosted website

Playback, drive scanning, Explorer, recycle bin, and the desktop shortcut only exist on his machine. A cloud deploy cannot see his disks and must not be given delete rights.

## Modules to build

```
app/titles.py    clean release names, year, SxxExx / Sesong folders
app/library.py   sqlite: items, episodes, progress, categories, settings
app/scan.py      walk drives, group into movie folders vs series vs loose files
app/posters.py   cache posters: iTunes search (movies), TVMaze (series), optional TMDB
app/player.py    find vlc.exe, launch with --start-time, poll status.xml, save position
app/trash.py     Windows SHFileOperation FO_DELETE | FOF_ALLOWUNDO; Linux XDG trash fallback
app/server.py    router, token check, static files, demo seed
web/*            Norwegian UI
assets/icon.png  and icon.ico (PNG-in-ICO is fine on Windows 10)
Installer.bat    repo root, CRLF, double-click
installer/lag-snarvei.ps1
tests/           unittest, no network
```

Paths are resolved from `Path(__file__).resolve().parent.parent`. Override data dir with env `MINEFILMER_DATA`.

## Library model

- Stable id: first 16 hex chars of SHA1 of `os.path.normcase(os.path.normpath(folder_or_file))`.
- `kind`: `movie` or `series`.
- `container`: `folder` (dedicated title folder, safe to recycle the whole folder) or `file` (loose file inside a pile like Downloads or `Filmer`; recycle that file plus same-stem subtitles only).
- Never recycle a drive root, a configured scan root, or any path that is not exactly a known library folder/file.
- Unplugged drives: keep the row, set `online=0`, show the path and "Disken er ikke koblet til". Do not delete library rows just because a drive is missing.
- Gone from a drive that **was** scanned: `missing=1`. Hide unless filter "Vis manglende".

### Grouping heuristic

- Video ext: mkv mp4 avi m4v wmv mov mpg mpeg ts m2ts webm
- Subtitle ext: srt sub ass ssa vtt idx
- Skip directory names (casefold): windows, program files, program files (x86), programdata, $recycle.bin, system volume information, recovery, perflogs, node_modules, appdata, application data, windows.old, intel, nvidia, amd, boot, efi, .git, and any name starting with `.`
- Do not follow symlinks.
- Ignore videos under 40 MB when a larger video exists in the same folder. Ignore names containing sample, trailer, sample.
- Season folders: `Season 1`, `Sesong 1`, `S01` → the series folder is the parent.
- Episode regex: `S01E02`, `1x02`, `Sesong 1 Episode 2`.
- A folder of otherwise unrelated videos whose name is generic (`Filmer`, `Movies`, `Downloads`, `Video`, `Serier`, `TV`, desktop, documents) is a **pile**: one item per file, `container=file`.
- One main video in a named folder → movie, `container=folder`.
- Two or more episode-pattern videos → series, `container=folder` on the series root.
- `cd1`/`cd2`/`part1` of one title → one movie; pass the parts to VLC in order.

## Playback

- Locate VLC: `where vlc`, then `C:\Program Files\VideoLAN\VLC\vlc.exe`, then `(x86)`, then settings override.
- Launch (no in-app player):

```
vlc.exe "<file>" --start-time=<seconds> --extraintf=http --http-host=127.0.0.1 --http-port=47632 --http-password=<random stored in data/vlc-password.txt>
```

- If saved position > 30s and < 90% of duration, resume at position−10s. If ≥ 90%, primary action starts from 0 and a secondary "Se igjen" is unnecessary — primary is "Spill av", small link "Fortsett er ferdig".
- Poll `http://127.0.0.1:47632/requests/status.xml` with Basic auth (empty user, password) every 5s while the process runs. Read `<time>` and `<length>`. Save on each poll and when the process exits.
- Progress key is the video path (normcase), so it survives rescans.
- Series "Fortsett" plays the episode with unfinished progress, else the next episode after the last finished one, else S01E01.
- Also allow "Merk som sett" / "Merk som ikke sett" when VLC's http interface is unavailable.
- If VLC is missing: big Norwegian message and https://www.videolan.org/vlc/ — do not fall open with another player.

## Posters

No API key required for the default path. Implemented in `app/posters.py`.

1. Optional TMDB v3 key in settings. If set, prefer `https://image.tmdb.org/t/p/w500{poster_path}`. Store the key in `data/` only, never commit it.
2. Wikidata search on the title (do **not** put the year in the search string; Wikidata then returns nothing). Score the description for film/series plus year. Prefer a portrait Wikipedia page image via the sitelink, then a Commons P18 thumbnail.
3. Wikipedia search (`pilicense=any`, `pithumbsize=480`) if Wikidata misses.
4. Series only: `https://api.tvmaze.com/singlesearch/shows?q={title}`.
5. One background thread, one title at a time. Cache bytes under `data/posters/<id>.img`. `poster` column: 0 unknown, 1 cached, 2 tried and missed.
6. Until a real image exists, `/poster/<id>` returns an SVG title card. Real images get a long cache; SVG placeholders must not.

## HTTP API (all JSON except `/`, assets, posters)

Inject a per-install token into the HTML as `<meta name="mine-token">`. Every POST requires header `X-Mine-Token`. If `Origin` is present it must be `http://127.0.0.1:47631` or `http://localhost:47631`. No CORS headers. This stops a random website from trashing his files.

- `GET /health`
- `GET /api/bootstrap` — summaries for every item (no episode lists), categories, scan status, whether vlc exists, continue-watching ids
- `GET /api/item/<id>` — episodes, subtitle count, path, progress per episode
- `POST /api/play` `{itemId, episodeId?, fromStart?}`
- `POST /api/progress` `{path, position, duration, finished?}`
- `POST /api/trash` `{itemId, episodeId?}` — episodeId set means that episode file + sidecars only
- `POST /api/reveal` `{itemId, episodeId?}` — `explorer /select,"path"`
- `POST /api/scan`
- `GET /api/scan`
- `POST /api/categories` `{name}` / `PATCH` rename / `DELETE`
- `POST /api/categories/<id>/items` `{itemId}` / `DELETE` that item
- `POST /api/settings` `{roots, tmdbKey, vlcPath}`
- `POST /api/browse-folder` — native folder dialog via PowerShell on Windows
- `POST /api/shortcut` — create/refresh the desktop .lnk
- `GET /poster/<id>`

Reject any static path containing `..`.

## UI (Norwegian, large, calm)

Warm cinema, not a Netflix logo copy: background `#12110f`, raised `#1c1a17`, text `#f7f3ea`, muted `#c9c0b2`, accent gold `#e8b86d`. Titles in Georgia (installed on Windows). UI in Segoe UI. Base font 18px. Buttons at least 44px tall. No hover-only controls.

Always-visible title under every poster (he cannot rely on hover). Path on the card can be the drive + folder in 16px `#c9c0b2`; the detail view shows the full path in a box.

Shell:

- Header: wordmark "Mine filmer", tall search "Søk etter film eller serie", button "Skann på nytt"
- Chips: Alle, Filmer, Serier, Ikke sett, Sett, one chip per category, "Ny kategori"
- Sort `<select>`: Tittel A–Å, Tittel Å–A, Nyest lagt til, Sist sett, Årstall
- Hero when something is unfinished: "Fortsett der du slapp", huge title, "Fortsett fra 1 t 4 min", full path, "Vis i Utforsker"
- Rows: Fortsett å se, Filmer, Serier, then each category. Horizontal scroll **and** arrow buttons. Cap a row at 24 cards plus "Vis alle".
- "Vis alle" and search results: grid, 24 per page, big "Neste" / "Forrige".
- Detail: Tilbake, poster, huge title, year, path box, "Kopier sti", "Vis i Utforsker", primary play, "Fra start", episodes as big rows, category checkboxes, "Legg i papirkurven".
- Context menu and Mer: Spill av, Fortsett, Fra start, Vis i Utforsker, Legg i kategori, Legg i papirkurven.
- Innstillinger (own view): folders to scan, paste path, "Bla gjennom", "Bruk alle disker", VLC path, optional TMDB key, "Lag snarvei på skrivebordet".
- Empty: "Ingen filmer funnet ennå. Koble til harddisken og trykk Skann på nytt."
- Scanning banner with live count. Do not freeze the page.
- Confirm trash by naming the folder. Tell him he can restore from Papirkurven.

Time format: `1 t 4 min`, not raw seconds. Search is case-insensitive and folds nothing incorrectly for æøå (use `toLocaleLowerCase('nb')`).

Demo: `python app/server.py --demo` seeds a small Norwegian-friendly library (include one movie at ~1 hour progress and a category "Norske filmer") and does not scan the agent machine. Real default scans.

## Windows installer

`Installer.bat` (CRLF), no admin:

1. `%LOCALAPPDATA%\MineFilmer`
2. Copy `app`, `web`, `assets`, launcher. Do not wipe existing `data`.
3. If `py -3` or `python` works, use it. Else download `https://www.python.org/ftp/python/3.12.7/python-3.12.7-embed-amd64.zip` into the install dir and unzip with `tar` (built into Win10) or PowerShell.
4. Write `Start.vbs` that starts `pythonw` (no console) if not already healthy, waits until `http://127.0.0.1:47631/health`, then opens the browser.
5. Desktop shortcut `Mine filmer.lnk` with `assets\icon.ico`, plus Start Menu.
6. SmartScreen note belongs in README: Mer info → Kjør likevel.

Root `Start Mine filmer.bat` is the same launcher for running from a git checkout.

## Tests

unittest for title cleaning, episode parsing, folder grouping on tmp trees, trash refusal of roots, category CRUD, resume math (1 hour → start-time 3610 or 3590 with the 10s backstep; document the chosen number in the test). No network in tests.

## Verify

- `python -m unittest discover -s tests`
- `python app/server.py --demo` and click through search, filter, category, detail, trash confirm (cancel), play (VLC missing message is acceptable on Linux).
- UI must show Norwegian copy and the 1-hour resume on the seeded movie.

## Out of scope

Accounts, cloud sync, transcoding, subtitles editor, scraping pirate sites, an in-browser player, Electron.

## Git

Work on the current branch (`main` unless `git symbolic-ref --short HEAD` says otherwise). Commit in slices. The public repository is `https://github.com/ganya002/filmer`, and `origin` points there. Push to `origin` when a slice is usable. Do not open a pull request unless Gabriel asks. Never print tokens or credentials.
