# Mine filmer

Et enkelt filmbibliotek til en Windows 10-PC. Ikonet **Mine filmer** på skrivebordet åpner siden. Den finner filmer og serier på PC-en og på harddisker som er plugget inn, viser store plakater og stor tekst, og spiller av i **VLC** fra der du slapp sist.

## Slik installerer du (Windows 10) – steg for steg

### Det du trenger

- En PC med Windows 10.
- Internett første gang (for å hente Python og plakater).
- **VLC** for å spille av filmene. Har du det ikke, last det ned fra [videolan.org](https://www.videolan.org/vlc/) først.

### Steg 1 – Last ned programmet

1. Åpne [github.com/ganya002/filmer](https://github.com/ganya002/filmer) i nettleseren.
2. Klikk den grønne **Code**-knappen, og velg **Download ZIP**.
3. Høyreklikk på zip-filen når den er lastet ned, og velg **Pakk ut alle**.
4. Legg den utpakkede mappen et sted du finner den igjen, for eksempel på Skrivebordet.

### Steg 2 – Installer

5. Åpne mappen og dobbelklikk **Installer.bat**.
6. Hvis Windows viser en blå advarsel om at filen ikke er gjenkjent: klikk **Mer info**, deretter **Kjør likevel**.
7. Et svart vindu åpnes og setter opp programmet. Første gang kan det ta noen minutter hvis Python må lastes ned. Ikke lukk vinduet mens det arbeider.
8. Når det er ferdig, åpnes **Mine filmer** automatisk i nettleseren.

### Steg 3 – Bruk det

9. Neste gang du skal se film, dobbelklikk ikonet **Mine filmer** på skrivebordet. Du trenger ikke skrive noen adresse.
10. Første gang trykker du **Skann på nytt** hvis listen er tom. Programmet leter i Videoer, Nedlastinger, Skrivebord, Dokumenter og på tilkoblede harddisker.
11. Filmer og serier åpnes i **VLC**. Hvis du har sett en time, tilbyr siden å fortsette der du slapp.

### Oppdatere programmet senere

1. Last ned en ny ZIP fra GitHub og pakk den ut.
2. Dobbelklikk **Installer.bat** på nytt.
3. Filmene, kategoriene og hvor langt du har kommet blir bevart.

### Hvis noe ikke virker

- **VLC mangler:** Installer VLC fra [videolan.org](https://www.videolan.org/vlc/), og trykk spill av igjen.
- **Ingen filmer funnet:** Koble til harddisken og trykk **Skann på nytt**. Du kan også legge til egne mapper under **Innstillinger**.
- **Siden åpnes ikke:** Dobbelklikk **Mine filmer** på skrivebordet en gang til. Vent noen sekunder – den første starten kan være treg på en gammel PC.

### Det du kan gjøre på siden

- Søke, og filtrere på film, serie, sett og ikke sett.
- Sortere på tittel, år, nyest og sist sett.
- Lage egne kategorier og legge filmer og serier i dem.
- Se nøyaktig mappe, og åpne den i Utforsker.
- Høyreklikke en tittel, eller trykke **Mer**, for å spille av, åpne mappen eller legge den i papirkurven.
- Legge en hel filmmappe (film og undertekster) i papirkurven. Der kan den hentes tilbake.
- Fortsette en film fra der VLC slapp, også etter at PC-en har vært avslått.

Siden snakker bare med denne PC-en. Den er ikke på internett, bortsett fra når den henter plakater.

Åpne siden i Microsoft Edge eller Chrome. Ikke i den gamle Internet Explorer.

## For the next agent

The app is implemented. Read [HANDOFF.md](HANDOFF.md) and [STATUS.json](STATUS.json) before changing it. UI language is Norwegian. Stack is stdlib Python plus `web/index.html`, `web/styles.css`, and `web/app.js`. Do not replace that with Next.js, Electron, or React. The server binds to `127.0.0.1:47631` only.

```bash
python3 app/server.py --demo
python3 -m unittest discover -s tests
```

Demo mode uses fake `D:\` paths and does not scan the machine. On Windows, `Installer.bat` copies the app to `%LOCALAPPDATA%\MineFilmer`, downloads embeddable Python only if needed, and creates the desktop shortcut **Mine filmer**.
