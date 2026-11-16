# PoliTO Sync

A small Windows app that downloads new course files from the Politecnico di Torino teaching portal
into your own folders. Click **Check** to see what's new, **Sync now** to download it.
It uses the official PoliTO Students API (https://github.com/polito/api-spec).

## Install (Windows, 5 minutes)

1. **Install Python** from https://www.python.org/downloads/windows/ — pick the
   **"Windows installer (64-bit)"**. On the first screen tick **"Add python.exe to PATH"**.
2. **Download this app**: on this GitHub page click the green **Code** button → **Download ZIP**,
   then unzip it somewhere (e.g. `Documents\PoliTO Sync`).
3. Double-click **`Setup.bat`** in the unzipped folder. If Python is in a custom folder and
   isn't found, it asks you to paste the path of `python.exe` (right-click it in File Explorer →
   *Copy as path*).
4. Open **PoliTO Sync** from your Desktop. The first time, a Settings window asks for your
   student ID, password and download folder (use **Browse…** to pick it). You can change them
   later with the **⚙ Settings** button.

Your password is stored only in the `.env` file on your own PC, in plain text. Don't share that file.

## How it works

- Each PoliTO course gets a folder in your download folder (default `Documents\Polito`).
  If you already have your own course folders, pick their parent folder in Settings and untick
  "Create a folder for each course"; folders are matched by course name (capitals and
  punctuation ignored). A course with no
  matching folder shows in orange; rename the folder or add `course_map.json`:
  `{"PoliTO course name": "My folder name"}`.
- Before downloading, the course folder (all subfolders) is scanned: files you already have are
  skipped (`Slides[1].pdf` and `Slides (2).pdf` count as `Slides.pdf`).
- New files go into `<course>\New\`. Your own files are never moved, changed or deleted.
- Each file is remembered (`data\state.json`), so it's never downloaded twice, even if you move or
  rename it. It's downloaded again only if the professor uploads a changed version.
- Videos/audio and files over 200 MB are skipped by default. All options are in `.env`.

## Troubleshooting

- **Login failed**: check your student ID and password in **⚙ Settings**.
- **The window doesn't open**: in the app folder run `.venv\Scripts\python polito_gui.pyw` in a
  Command Prompt to see the error. `No module named tkinter` → re-run the Python installer,
  choose *Modify* and tick *tcl/tk*.
- Full log: `data\sync.log`.

## For developers

Command line: `.venv\Scripts\python polito_sync.py [--dry-run] [--init-only] [-v]`.
Tests: `python -m unittest discover -s tests`.
Unofficial tool, not affiliated with Politecnico di Torino. Use at your own risk.
