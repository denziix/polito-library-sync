# polito-library-sync

Automatically downloads new course files from the PoliTO teaching portal into a local folder.
It uses the official PoliTO Students API (https://github.com/polito/api-spec) and only fetches
files it has not seen before (or whose checksum changed).

## Setup (Windows)

```bat
git clone https://github.com/denziix/polito-library-sync
cd polito-library-sync
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
```

Edit `.env` with your student ID and password (git-ignored, never commit it).

## First run

```bat
.venv\Scripts\python polito_sync.py --dry-run -v    # preview only
.venv\Scripts\python polito_sync.py --init-only     # (optional) mark everything as already seen
.venv\Scripts\python polito_sync.py                 # download
```

How it decides what to download:
- Each PoliTO course is matched to an existing folder in `POLITO_DOWNLOAD_DIR` by name
  (case and punctuation ignored). Unmatched courses are skipped and named in the log; fix them by
  renaming the folder or adding `course_map.json`, e.g. `{"PoliTO course name": "My folder"}`.
- The whole course folder (all subfolders) is scanned; a file you already have, under any
  subfolder, is not downloaded again (`Slides[1].pdf` and `Slides (2).pdf` count as `Slides.pdf`).
- Missing files go into `<course>\New\`. Your own files are never moved, changed or deleted.
- Videos/audio and files over 200 MB are skipped; only courses in your study plan are checked.

## Run automatically (Task Scheduler)

Create a task: trigger every 1 hour, action "Start a program" -> `run_sync.bat`
(or run `schtasks /Create /SC HOURLY /TN PolitoSync /TR "C:\full\path\run_sync.bat"`).

## Tests

```bat
python -m unittest discover -s tests
```

## Notes

- Login uses your username and password. If PoliTO requires MFA for this login type, login will
  fail with a clear error; see the log in `data\sync.log`.
- Runtime data (login token, state, log) lives in `data/`, which is git-ignored.
