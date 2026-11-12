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

By default files go to `Documents\Polito\<course>\...`, videos/audio and files over 200 MB are
skipped, and only courses in your personal study plan are checked. See `.env.example`.

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
