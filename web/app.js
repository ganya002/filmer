(function () {
  const token = document.querySelector('meta[name="mine-token"]').content;
  const view = document.getElementById("view");
  const filters = document.getElementById("filters");
  const banner = document.getElementById("banner");
  const menu = document.getElementById("menu");
  const dialog = document.getElementById("dialog");
  const toast = document.getElementById("toast");
  const search = document.getElementById("q");

  let library = { items: [], categories: [], scan: {}, demo: false, vlc: false, roots: [] };
  let ui = {
    q: "",
    kind: "alle",
    watched: "alle",
    category: "",
    sort: "tittel",
    page: 0,
  };
  let detail = null;
  let toastTimer = 0;
  let pollTimer = 0;

  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }

  function api(path, body) {
    const opts = { headers: {} };
    if (body !== undefined) {
      opts.method = "POST";
      opts.headers["Content-Type"] = "application/json";
      opts.headers["X-Mine-Token"] = token;
      opts.body = JSON.stringify(body);
    }
    return fetch(path, opts).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (data) {
        data._status = res.status;
        return data;
      });
    });
  }

  function say(text) {
    toast.hidden = false;
    toast.textContent = text;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toast.hidden = true; }, 4200);
  }

  function itemById(id) {
    return library.items.find(function (item) { return item.id === id; });
  }

  function catById(id) {
    return library.categories.find(function (cat) { return cat.id === id; });
  }

  function shortPath(path) {
    const parts = String(path || "").split(/[\\/]/).filter(Boolean);
    if (!parts.length) return "";
    if (parts.length === 1) return parts[0];
    return parts.slice(-2).join("\\");
  }

  function watchedState(item) {
    const mode = item.resume && item.resume.mode;
    if (mode === "finished") return "sett";
    return "usett";
  }

  function filtered() {
    const q = search.value.trim().toLocaleLowerCase("nb");
    let list = library.items.filter(function (item) {
      if (ui.kind === "film" && item.kind !== "movie") return false;
      if (ui.kind === "serie" && item.kind !== "series") return false;
      if (ui.watched === "sett" && watchedState(item) !== "sett") return false;
      if (ui.watched === "usett" && watchedState(item) === "sett") return false;
      if (ui.category && item.categories.indexOf(ui.category) === -1) return false;
      if (!q) return true;
      const hay = (item.title + " " + (item.year || "") + " " + item.folder).toLocaleLowerCase("nb");
      return hay.indexOf(q) !== -1;
    });
    const sort = ui.sort;
    list = list.slice().sort(function (a, b) {
      if (a.online !== b.online) return a.online ? -1 : 1;
      if (sort === "tittel-z") return b.title.localeCompare(a.title, "nb", { sensitivity: "base" });
      if (sort === "nyest") return (b.mtime || 0) - (a.mtime || 0);
      if (sort === "sist") return ((b.resume && b.resume.updated) || 0) - ((a.resume && a.resume.updated) || 0);
      if (sort === "aar") return (b.year || 0) - (a.year || 0) || a.title.localeCompare(b.title, "nb");
      return a.title.localeCompare(b.title, "nb", { sensitivity: "base" });
    });
    return list;
  }

  function continueItems() {
    return library.items
      .filter(function (item) {
        const mode = item.resume && item.resume.mode;
        return item.online && (mode === "resume" || mode === "next");
      })
      .sort(function (a, b) { return (b.resume.updated || 0) - (a.resume.updated || 0); });
  }

  function poster(item) {
    return '<img src="/poster/' + esc(item.id) + '" alt="" width="200" height="300" loading="lazy">';
  }

  function card(item) {
    const kind = item.kind === "series" ? "Serie" : "Film";
    const year = item.year ? item.year + " · " : "";
    const where = item.online ? shortPath(item.folder) : "Disken er ikke koblet til";
    const resume = item.resume || {};
    const pct = resume.duration ? Math.max(0, Math.min(100, (resume.position / resume.duration) * 100)) : 0;
    const bar = pct >= 2 && resume.mode !== "start"
      ? '<div class="bar"><span style="width:' + pct.toFixed(1) + '%"></span></div>'
      : "";
    return (
      '<article class="card' + (item.online ? "" : " off") + '" data-id="' + esc(item.id) + '">' +
        '<div class="poster-wrap">' +
          '<button type="button" class="poster-hit" data-action="open" data-id="' + esc(item.id) + '">' +
            poster(item) + bar +
          "</button>" +
          '<button type="button" class="more" data-action="menu" data-id="' + esc(item.id) + '">Mer</button>' +
        "</div>" +
        '<button type="button" class="card-title" data-action="open" data-id="' + esc(item.id) + '">' + esc(item.title) + "</button>" +
        '<p class="meta">' + esc(year + kind) + "</p>" +
        '<p class="meta">' + esc(where) + "</p>" +
        (resume.label && resume.mode !== "start" ? '<p class="meta">' + esc(resume.label) + "</p>" : "") +
      "</article>"
    );
  }

  function row(title, items, action) {
    if (!items.length) return "";
    const shown = items.slice(0, 24).map(card).join("");
    const more = items.length > 24
      ? '<button type="button" class="btn ghost" data-action="' + action.action + '" data-kind="' + esc(action.kind || "") + '" data-cat="' + esc(action.cat || "") + '">Vis alle</button>'
      : "";
    return (
      '<section class="section">' +
        '<div class="row-head"><h2>' + esc(title) + "</h2>" + more + "</div>" +
        '<div class="row-line">' +
          '<button type="button" class="arrow" data-action="scroll" data-dir="-1" aria-label="Rull til venstre">‹</button>' +
          '<div class="scroller">' + shown + "</div>" +
          '<button type="button" class="arrow" data-action="scroll" data-dir="1" aria-label="Rull til høyre">›</button>' +
        "</div>" +
      "</section>"
    );
  }

  function renderFilters() {
    const chips = [
      ["alle", "Alle", "kind"],
      ["film", "Filmer", "kind"],
      ["serie", "Serier", "kind"],
      ["usett", "Ikke sett", "watched"],
      ["sett", "Sett", "watched"],
    ];
    let html = chips.map(function (chip) {
      const on = (chip[2] === "kind" ? ui.kind : ui.watched) === chip[0];
      return '<button type="button" class="chip' + (on ? " on" : "") + '" data-action="chip" data-group="' + chip[2] + '" data-value="' + chip[0] + '">' + chip[1] + "</button>";
    }).join("");
    html += library.categories.map(function (cat) {
      const on = ui.category === cat.id;
      return '<button type="button" class="chip' + (on ? " on" : "") + '" data-action="cat" data-id="' + esc(cat.id) + '">' + esc(cat.name) + "</button>";
    }).join("");
    html += '<button type="button" class="chip" data-action="new-cat">Ny kategori</button>';
    html += '<label class="sr" for="sort">Sorter</label><select id="sort" aria-label="Sorter">' +
      option("tittel", "Tittel A–Å") +
      option("tittel-z", "Tittel Å–A") +
      option("nyest", "Nyest lagt til") +
      option("sist", "Sist sett") +
      option("aar", "Årstall") +
      "</select>";
    filters.innerHTML = html;
    const sort = document.getElementById("sort");
    sort.value = ui.sort;
    sort.addEventListener("change", function () {
      ui.sort = sort.value;
      ui.page = 0;
      renderView();
    });
  }

  function option(value, label) {
    return '<option value="' + value + '">' + label + "</option>";
  }

  function renderHome() {
    const cont = continueItems();
    const movies = library.items.filter(function (item) { return item.kind === "movie"; });
    const series = library.items.filter(function (item) { return item.kind === "series"; });
    let html = "";
    if (cont[0]) {
      const item = cont[0];
      html +=
        '<section class="hero">' +
          poster(item) +
          "<div>" +
            '<p class="kicker">Fortsett der du slapp</p>' +
            "<h1>" + esc(item.title) + "</h1>" +
            '<p class="path">' + esc(item.folder) + "</p>" +
            '<div class="actions">' +
              '<button type="button" class="btn primary" data-action="play" data-id="' + esc(item.id) + '">' + esc(item.resume.label || "Spill av") + "</button>" +
              '<button type="button" class="btn" data-action="open" data-id="' + esc(item.id) + '">Mer om filmen</button>' +
              '<button type="button" class="btn" data-action="reveal" data-id="' + esc(item.id) + '">Vis i Utforsker</button>' +
            "</div>" +
          "</div>" +
        "</section>";
    }
    html += row("Fortsett å se", cont, { action: "show-continue" });
    html += row("Filmer", movies, { action: "show-kind", kind: "film" });
    html += row("Serier", series, { action: "show-kind", kind: "serie" });
    library.categories.forEach(function (cat) {
      const items = library.items.filter(function (item) { return item.categories.indexOf(cat.id) !== -1; });
      html += row(cat.name, items, { action: "show-cat", cat: cat.id });
    });
    if (!library.items.length) {
      html += '<div class="empty">Ingen filmer funnet ennå. Koble til harddisken og trykk Skann på nytt.</div>';
    }
    html += '<p class="foot">Filmene spilles i VLC. Siden kjører bare på denne PC-en.</p>';
    view.innerHTML = html;
  }

  function heading() {
    if (search.value.trim()) return "Treff";
    if (ui.kind === "film") return "Filmer";
    if (ui.kind === "serie") return "Serier";
    if (ui.watched === "sett") return "Sett";
    if (ui.watched === "usett") return "Ikke sett";
    if (ui.category) {
      const cat = catById(ui.category);
      return cat ? cat.name : "Kategori";
    }
    if (ui.continueOnly) return "Fortsett å se";
    return "Alle";
  }

  function renderGrid() {
    const list = ui.continueOnly ? continueItems() : filtered();
    const size = 24;
    const pages = Math.max(1, Math.ceil(list.length / size));
    if (ui.page >= pages) ui.page = pages - 1;
    const slice = list.slice(ui.page * size, ui.page * size + size);
    let html = '<div class="page-head"><h2>' + esc(heading()) + '</h2><p class="meta">' + list.length + "</p></div>";
    if (!slice.length) {
      html += '<div class="empty">Ingen treff. Prøv et annet søk, eller skann på nytt.</div>';
    } else {
      html += '<div class="grid">' + slice.map(card).join("") + "</div>";
    }
    if (pages > 1) {
      html += '<div class="pager" style="margin-top:18px">' +
        '<button type="button" class="btn" data-action="page" data-dir="-1"' + (ui.page === 0 ? " disabled" : "") + ">Forrige</button>" +
        "<span>Side " + (ui.page + 1) + " av " + pages + "</span>" +
        '<button type="button" class="btn" data-action="page" data-dir="1"' + (ui.page + 1 >= pages ? " disabled" : "") + ">Neste</button>" +
        "</div>";
    }
    view.innerHTML = html;
  }

  function renderDetail() {
    if (!detail) {
      view.innerHTML = '<p class="note">Henter …</p>';
      return;
    }
    const item = detail;
    const kind = item.kind === "series" ? "Serie" : "Film";
    const resume = item.resume || {};
    let episodes = "";
    if (item.kind === "series") {
      episodes = '<div class="episodes">' + item.episodes.map(function (ep) {
        const mark = ep.finished ? "Sett" : (ep.position >= 30 ? "Fortsett fra " + formatMinute(ep.position) : "Ikke startet");
        return '<button type="button" class="ep" data-action="play" data-id="' + esc(item.id) + '" data-episode="' + esc(ep.id) + '">' +
          "<span>" + esc(ep.title) + "</span><small>" + esc(mark) + "</small></button>";
      }).join("") + "</div>";
    }
    const cats = library.categories.map(function (cat) {
      const on = item.categories.indexOf(cat.id) !== -1;
      return '<label><input type="checkbox" data-action="member" data-cat="' + esc(cat.id) + '"' + (on ? " checked" : "") + "> " + esc(cat.name) + "</label>";
    }).join("");
    view.innerHTML =
      '<p><button type="button" class="btn" data-action="back">Tilbake</button></p>' +
      '<article class="detail">' +
        '<div class="poster-wrap">' + poster(item) + "</div>" +
        "<div>" +
          '<p class="kicker">' + kind + (item.year ? " · " + item.year : "") + "</p>" +
          "<h1>" + esc(item.title) + "</h1>" +
          (item.online ? "" : '<p class="note">Disken er ikke koblet til.</p>') +
          "<h2 style=\"font-size:22px;margin-top:18px\">Hvor den ligger</h2>" +
          '<div class="path-box">' + esc(item.folder) + "</div>" +
          '<div class="actions">' +
            '<button type="button" class="btn primary" data-action="play" data-id="' + esc(item.id) + '">' + esc(resume.label || "Spill av") + "</button>" +
            '<button type="button" class="btn" data-action="play" data-id="' + esc(item.id) + '" data-from-start="1">Fra start</button>' +
            '<button type="button" class="btn" data-action="reveal" data-id="' + esc(item.id) + '">Vis i Utforsker</button>' +
            '<button type="button" class="btn" data-action="copy" data-path="' + esc(item.folder) + '">Kopier sti</button>' +
          "</div>" +
          '<p class="meta">Undertekster i mappen: ' + (item.subtitleCount || 0) + "</p>" +
          '<div class="actions" style="margin-top:14px">' +
            '<button type="button" class="btn" data-action="watched" data-finished="1">Merk som sett</button>' +
            '<button type="button" class="btn" data-action="watched" data-finished="0">Merk som ikke sett</button>' +
            '<button type="button" class="btn danger" data-action="trash" data-id="' + esc(item.id) + '">Legg i papirkurven</button>' +
          "</div>" +
          '<h2 style="font-size:22px;margin-top:22px">Kategorier</h2>' +
          '<div class="checks">' + (cats || "<p class=\"meta\">Ingen kategorier ennå.</p>") + "</div>" +
          '<button type="button" class="btn" data-action="new-cat">Ny kategori</button>' +
          episodes +
        "</div>" +
      "</article>";
  }

  function formatMinute(seconds) {
    seconds = Math.floor(Number(seconds) || 0);
    if (seconds < 30) return "under ett minutt";
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    if (hours && minutes) return hours + " t " + minutes + " min";
    if (hours) return hours + " t";
    if (minutes) return minutes + " min";
    return "under ett minutt";
  }

  function renderSettings() {
    const roots = (library.roots || []).map(function (root) {
      return '<div class="root"><span>' + esc(root) + '</span><button type="button" class="btn ghost" data-action="drop-root" data-path="' + esc(root) + '">Fjern</button></div>';
    }).join("");
    view.innerHTML =
      '<div class="settings">' +
        '<p><button type="button" class="btn" data-action="back">Tilbake</button></p>' +
        "<h1>Innstillinger</h1>" +
        "<p>Tom liste betyr at vi leter i Videoer, Nedlastinger, Skrivebord, Dokumenter og på alle andre disker. C: skannes ikke fra rot, det er for tregt.</p>" +
        '<div class="field"><h2>Mapper</h2><div class="roots">' + (roots || "<p class=\"meta\">Standardmapper.</p>") + "</div>" +
          '<input id="root-input" type="text" placeholder="Lim inn en sti, for eksempel D:\\Filmer">' +
          '<div class="actions"><button type="button" class="btn" id="add-root">Legg til mappe</button>' +
          '<button type="button" class="btn" id="browse">Bla gjennom</button>' +
          '<button type="button" class="btn ghost" id="clear-roots">Bruk standardmapper</button></div></div>' +
        '<div class="field"><h2>VLC</h2><p class="meta">La feltet stå tomt hvis VLC ligger på vanlig sted.</p>' +
          '<input id="vlc-path" type="text" value="' + esc(library.vlcPath || "") + '" placeholder="C:\\Program Files\\VideoLAN\\VLC\\vlc.exe"></div>' +
        '<div class="field"><h2>Flere plakater</h2><p class="meta">Valgfritt. Uten nøkkel hentes bilder fra Wikipedia og TVMaze. En gratis nøkkel fra themoviedb.org gir ofte penere plakater.</p>' +
          '<input id="tmdb-key" type="password" value="' + esc(library.tmdbKey || "") + '" autocomplete="off"></div>' +
        '<div class="actions"><button type="button" class="btn primary" id="save-settings">Lagre</button>' +
          '<button type="button" class="btn" id="make-shortcut">Lag snarvei på skrivebordet</button></div>' +
      "</div>";
    document.getElementById("add-root").onclick = function () {
      const value = document.getElementById("root-input").value.trim();
      if (!value) return;
      const next = (library.roots || []).concat([value]);
      saveSettings({ roots: next });
    };
    document.getElementById("browse").onclick = function () {
      api("/api/browse-folder", {}).then(function (res) {
        if (res.path) document.getElementById("root-input").value = res.path;
        else say(res.error || "Fant ingen mappe.");
      });
    };
    document.getElementById("clear-roots").onclick = function () {
      saveSettings({ roots: [] });
    };
    document.getElementById("save-settings").onclick = function () {
      saveSettings({
        roots: library.roots || [],
        vlcPath: document.getElementById("vlc-path").value,
        tmdbKey: document.getElementById("tmdb-key").value,
      });
    };
    document.getElementById("make-shortcut").onclick = function () {
      api("/api/shortcut", {}).then(function (res) {
        say(res.ok ? "Snarveien Mine filmer ligger på skrivebordet." : (res.error || "Klarte ikke å lage snarveien."));
      });
    };
  }

  function saveSettings(extra) {
    api("/api/settings", extra).then(function (res) {
      if (res.error) say(res.error);
      else say("Lagret.");
      return refresh();
    }).then(function () {
      if (location.hash === "#/innstillinger") renderSettings();
    });
  }

  function isGrid() {
    return !!(
      search.value.trim() ||
      ui.kind !== "alle" ||
      ui.watched !== "alle" ||
      ui.category ||
      ui.continueOnly
    );
  }

  function renderView() {
    closeMenu();
    if (location.hash === "#/innstillinger") {
      filters.hidden = true;
      renderSettings();
      return;
    }
    filters.hidden = false;
    if (location.hash.indexOf("#/film/") === 0) {
      renderDetail();
      return;
    }
    if (isGrid()) renderGrid();
    else renderHome();
  }

  function render() {
    renderFilters();
    renderView();
  }

  function refresh() {
    return api("/api/bootstrap").then(function (data) {
      library.items = data.items || [];
      library.categories = data.categories || [];
      library.scan = data.scan || {};
      library.demo = !!data.demo;
      library.vlc = !!data.vlc;
      library.roots = data.roots || [];
      return api("/api/settings");
    }).then(function (settings) {
      if (settings && settings.vlcPath !== undefined) {
        library.vlcPath = settings.vlcPath;
        library.tmdbKey = settings.tmdbKey;
        library.roots = settings.roots || library.roots;
      }
      if (detail) {
        const known = itemById(detail.id);
        if (known) detail.categories = known.categories.slice();
      }
      updateBanner();
      render();
    }).catch(function () {
      view.innerHTML = '<div class="empty">Fikk ikke kontakt med Mine filmer på denne PC-en. Prøv ikonet på skrivebordet en gang til.</div>';
    });
  }

  function updateBanner() {
    const scan = library.scan || {};
    if (scan.running) {
      banner.hidden = false;
      const where = scan.current ? " Ser i " + scan.current + "." : "";
      banner.textContent = "Ser etter filmer … " + (scan.found || 0) + " så langt." + where;
    } else if (scan.error) {
      banner.hidden = false;
      banner.textContent = scan.error;
    } else {
      banner.hidden = true;
    }
  }

  function poll() {
    clearTimeout(pollTimer);
    api("/api/scan").then(function (scan) {
      const before = (library.scan && library.scan.found) || 0;
      library.scan = scan;
      updateBanner();
      const grew = (scan.found || 0) !== before;
      if (!scan.running || (grew && (scan.found < 40 || scan.found % 15 === 0))) {
        return refresh();
      }
    }).finally(function () {
      if (library.scan && library.scan.running) pollTimer = setTimeout(poll, 1600);
    });
  }

  function openDetail(id) {
    detail = null;
    if (location.hash !== "#/film/" + id) location.hash = "#/film/" + id;
    renderView();
    api("/api/item/" + id).then(function (data) {
      if (data.error) {
        say(data.error);
        return;
      }
      detail = data;
      const known = itemById(id);
      if (known) detail.categories = known.categories;
      if (location.hash === "#/film/" + id) renderDetail();
    });
  }

  function play(id, episodeId, fromStart) {
    const body = { itemId: id, fromStart: !!fromStart };
    if (episodeId) body.episodeId = episodeId;
    api("/api/play", body).then(function (res) {
      if (res.ok) {
        say(fromStart ? "Åpner i VLC fra start." : "Åpner i VLC.");
        return;
      }
      if (res.code === "vlc-missing") {
        openDialog(
          "VLC ble ikke funnet",
          "<p>Filmene spilles bare i VLC, ikke i nettleseren. Installer VLC, og trykk Spill av igjen.</p>" +
            '<p><a href="https://www.videolan.org/vlc/" target="_blank" rel="noopener">Last ned VLC</a></p>',
          '<button type="button" class="btn primary" data-action="close-dialog">Lukk</button>'
        );
        return;
      }
      say(res.error || "Kunne ikke åpne filmen.");
    });
  }

  function openDialog(title, body, buttons) {
    dialog.hidden = false;
    dialog.innerHTML =
      '<div class="dialog" role="dialog" aria-modal="true">' +
        "<h2>" + esc(title) + "</h2>" + body +
        '<div class="actions" style="margin-top:16px">' + buttons + "</div>" +
      "</div>";
    const focus = dialog.querySelector("button, input");
    if (focus) focus.focus();
  }

  function closeDialog() {
    dialog.hidden = true;
    dialog.innerHTML = "";
  }

  function closeMenu() {
    menu.hidden = true;
    menu.innerHTML = "";
  }

  function openMenu(x, y, id) {
    const item = itemById(id);
    if (!item) return;
    menu.innerHTML =
      '<button type="button" data-action="play" data-id="' + esc(id) + '">Spill av</button>' +
      '<button type="button" data-action="play" data-id="' + esc(id) + '" data-from-start="1">Fra start</button>' +
      '<button type="button" data-action="reveal" data-id="' + esc(id) + '">Vis i Utforsker</button>' +
      '<button type="button" data-action="add-to-cat" data-id="' + esc(id) + '">Legg i kategori</button>' +
      '<button type="button" data-action="trash" data-id="' + esc(id) + '">Legg i papirkurven</button>';
    menu.hidden = false;
    menu.style.left = "8px";
    menu.style.top = "8px";
    const rect = menu.getBoundingClientRect();
    const left = Math.max(8, Math.min(x, window.innerWidth - rect.width - 8));
    const top = Math.max(8, Math.min(y, window.innerHeight - rect.height - 8));
    menu.style.left = left + "px";
    menu.style.top = top + "px";
  }

  function askTrash(id, episodeId) {
    const item = detail && detail.id === id ? detail : itemById(id);
    if (!item) return;
    const folder = item.folder;
    const whole = !episodeId;
    const lead = whole
      ? "Vil du legge hele mappen i papirkurven?"
      : "Vil du legge denne episoden i papirkurven?";
    openDialog(
      "Papirkurv",
      "<p>" + lead + "</p><div class=\"path-box\">" + esc(folder) + "</div><p>Du kan hente det tilbake fra papirkurven i Windows.</p>",
      '<button type="button" class="btn danger" id="confirm-trash">Legg i papirkurven</button>' +
        '<button type="button" class="btn" data-action="close-dialog">Avbryt</button>'
    );
    document.getElementById("confirm-trash").onclick = function () {
      closeDialog();
      const body = { itemId: id };
      if (episodeId) body.episodeId = episodeId;
      api("/api/trash", body).then(function (res) {
        say(res.ok ? "Lagt i papirkurven." : (res.error || "Ble ikke lagt i papirkurven."));
        if (res.ok) {
          detail = null;
          location.hash = "#/";
          refresh();
        }
      });
    };
  }

  function askCategory() {
    openDialog(
      "Ny kategori",
      '<label>Navn<input id="cat-name" type="text" maxlength="40" placeholder="For eksempel Norske filmer"></label>',
      '<button type="button" class="btn primary" id="save-cat">Lagre</button><button type="button" class="btn" data-action="close-dialog">Avbryt</button>'
    );
    const input = document.getElementById("cat-name");
    input.focus();
    document.getElementById("save-cat").onclick = function () {
      api("/api/categories", { name: input.value }).then(function (res) {
        if (res.error) say(res.error);
        else {
          closeDialog();
          refresh();
        }
      });
    };
  }

  function askMembership(id) {
    const item = itemById(id);
    if (!item) return;
    if (!library.categories.length) {
      askCategory();
      return;
    }
    const boxes = library.categories.map(function (cat) {
      const on = item.categories.indexOf(cat.id) !== -1;
      return '<label><input type="checkbox" data-cat="' + esc(cat.id) + '"' + (on ? " checked" : "") + "> " + esc(cat.name) + "</label>";
    }).join("");
    openDialog(
      "Legg i kategori",
      '<div class="checks">' + boxes + "</div>",
      '<button type="button" class="btn primary" id="save-member">Ferdig</button>'
    );
    document.getElementById("save-member").onclick = function () {
      const jobs = Array.from(dialog.querySelectorAll("input[type=checkbox]")).map(function (box) {
        return api("/api/categories/items", {
          categoryId: box.getAttribute("data-cat"),
          itemId: id,
          include: box.checked,
        });
      });
      Promise.all(jobs).then(function () {
        closeDialog();
        refresh();
      });
    };
  }

  document.body.addEventListener("click", function (event) {
    const target = event.target.closest("[data-action]");
    if (menu.hidden === false && !event.target.closest("#menu")) closeMenu();
    if (!target) return;
    const action = target.getAttribute("data-action");
    const id = target.getAttribute("data-id");
    if (action === "chip") {
      const group = target.getAttribute("data-group");
      const value = target.getAttribute("data-value");
      if (group === "kind") ui.kind = ui.kind === value && value !== "alle" ? "alle" : value;
      if (group === "watched") ui.watched = ui.watched === value ? "alle" : value;
      ui.category = "";
      ui.continueOnly = false;
      ui.page = 0;
      if (location.hash !== "#/") location.hash = "#/";
      else render();
      return;
    }
    if (action === "cat") {
      const cat = target.getAttribute("data-id");
      ui.category = ui.category === cat ? "" : cat;
      ui.kind = "alle";
      ui.continueOnly = false;
      ui.page = 0;
      if (location.hash !== "#/") location.hash = "#/";
      else render();
      return;
    }
    if (action === "show-kind") {
      ui.kind = target.getAttribute("data-kind");
      ui.category = "";
      ui.continueOnly = false;
      ui.page = 0;
      location.hash = "#/";
      render();
      return;
    }
    if (action === "show-cat") {
      ui.category = target.getAttribute("data-cat");
      ui.kind = "alle";
      ui.continueOnly = false;
      ui.page = 0;
      location.hash = "#/";
      render();
      return;
    }
    if (action === "show-continue") {
      ui.continueOnly = true;
      ui.kind = "alle";
      ui.category = "";
      ui.page = 0;
      location.hash = "#/";
      render();
      return;
    }
    if (action === "page") {
      ui.page += Number(target.getAttribute("data-dir"));
      renderView();
      view.focus();
      return;
    }
    if (action === "scroll") {
      const scroller = target.parentElement.querySelector(".scroller");
      if (scroller) scroller.scrollBy({ left: Number(target.getAttribute("data-dir")) * 420 });
      return;
    }
    if (action === "open") {
      openDetail(id);
      return;
    }
    if (action === "menu") {
      const rect = target.getBoundingClientRect();
      openMenu(rect.left, rect.bottom + 4, id);
      event.stopPropagation();
      return;
    }
    if (action === "play") {
      closeMenu();
      play(id, target.getAttribute("data-episode"), target.getAttribute("data-from-start") === "1");
      return;
    }
    if (action === "reveal") {
      closeMenu();
      api("/api/reveal", { itemId: id }).then(function (res) {
        if (!res.ok) say(res.error || "Kunne ikke åpne Utforsker.");
      });
      return;
    }
    if (action === "copy") {
      const path = target.getAttribute("data-path") || "";
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(path).then(function () { say("Stien er kopiert."); }, function () { say(path); });
      } else say(path);
      return;
    }
    if (action === "trash") {
      closeMenu();
      askTrash(id, target.getAttribute("data-episode"));
      return;
    }
    if (action === "add-to-cat") {
      closeMenu();
      askMembership(id);
      return;
    }
    if (action === "new-cat") {
      askCategory();
      return;
    }
    if (action === "watched") {
      api("/api/progress", {
        itemId: detail && detail.id,
        finished: target.getAttribute("data-finished") === "1",
      }).then(function () {
        return refresh();
      }).then(function () {
        if (detail) openDetail(detail.id);
      });
      return;
    }
    if (action === "member") return;
    if (action === "back") {
      location.hash = "#/";
      return;
    }
    if (action === "close-dialog") closeDialog();
    if (action === "drop-root") {
      const path = target.getAttribute("data-path");
      saveSettings({ roots: (library.roots || []).filter(function (root) { return root !== path; }) });
    }
  });

  document.body.addEventListener("change", function (event) {
    const box = event.target;
    if (box.getAttribute("data-action") !== "member" || !detail) return;
    api("/api/categories/items", {
      categoryId: box.getAttribute("data-cat"),
      itemId: detail.id,
      include: box.checked,
    }).then(function () { return refresh(); });
  });

  document.addEventListener("contextmenu", function (event) {
    const card = event.target.closest("[data-id]");
    if (!card) return;
    event.preventDefault();
    openMenu(event.clientX, event.clientY, card.getAttribute("data-id"));
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      closeMenu();
      closeDialog();
    }
    if (event.key === "/" && document.activeElement !== search && !event.target.closest("input, textarea")) {
      event.preventDefault();
      search.focus();
    }
  });

  document.getElementById("scan").onclick = function () {
    api("/api/scan", {}).then(function () {
      library.scan = { running: true, found: library.scan.found || 0, current: "" };
      updateBanner();
      poll();
    });
  };
  document.getElementById("settings").onclick = function () {
    location.hash = "#/innstillinger";
  };
  search.addEventListener("input", function () {
    ui.q = search.value;
    ui.page = 0;
    ui.continueOnly = false;
    if (location.hash !== "#/" && location.hash.indexOf("#/film/") !== 0) location.hash = "#/";
    if (location.hash.indexOf("#/film/") === 0) location.hash = "#/";
    else render();
  });

  window.addEventListener("hashchange", function () {
    if (location.hash.indexOf("#/film/") === 0) {
      const id = decodeURIComponent(location.hash.slice(7));
      if (!detail || detail.id !== id) openDetail(id);
      else renderView();
      return;
    }
    render();
  });

  function watchPosters() {
    let tries = 0;
    function tick() {
      const waiting = library.items.some(function (item) { return item.poster === 0; });
      if (!waiting || tries > 24) return;
      tries += 1;
      setTimeout(function () {
        api("/api/bootstrap").then(function (data) {
          const next = {};
          (data.items || []).forEach(function (item) { next[item.id] = item.poster; });
          let changed = false;
          library.items.forEach(function (item) {
            if (next[item.id] !== undefined && item.poster !== next[item.id]) {
              item.poster = next[item.id];
              changed = true;
            }
          });
          if (changed) {
            document.querySelectorAll('img[src^="/poster/"]').forEach(function (img) {
              img.src = img.getAttribute("src").split("?")[0] + "?v=" + Date.now();
            });
          }
          tick();
        }).catch(function () { tick(); });
      }, 4000);
    }
    tick();
  }

  view.textContent = "Henter biblioteket …";
  refresh().then(function () {
    watchPosters();
    if (library.scan && library.scan.running) poll();
    if (location.hash.indexOf("#/film/") === 0) {
      openDetail(decodeURIComponent(location.hash.slice(7)));
    }
  });
})();
