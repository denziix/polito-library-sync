# PoliTO Sync (polito-library-sync)

Windows app that downloads new course files from the Politecnico di Torino teaching portal into
the user's own course folders. Shared with friends via GitHub (they use Download ZIP + Setup.bat).

## Files
- `polito_sync.py` - core: config (.env), API client, sync logic, CLI (`--dry-run`, `--init-only`, `-v`).
- `polito_gui.pyw` - tkinter app window (Sync now / Check / Open folder / Settings), runs sync in a
  thread and gets progress via `sync(..., progress=callback)` events: "courses", "course", "file".
  First launch opens a Settings dialog that writes `.env` (keeps other lines intact).
- `Setup.bat` - friend installer: finds Python (py launcher, PATH, or asks for python.exe path),
  creates `.venv`, installs requirements + winotify, checks tkinter, creates desktop shortcut.
- `Create desktop shortcut.bat` - "PoliTO Sync.lnk" -> `.venv\Scripts\pythonw.exe polito_gui.pyw`, icon `assets/icon.ico`.
- `Sync PoliTO.bat` (opens GUI), `run_sync.bat` (headless, for Task Scheduler).
- `tests/test_sync.py` - unittest with a FakeApi; run `python -m unittest discover -s tests`.

## PoliTO API (official spec: github.com/polito/api-spec, dist/clients/student/openapi.yaml)
- Base `https://app.didattica.polito.it/api`, Bearer token.
- `POST /auth/login` body: `{loginType:"basic", username, password, preferences:{language:"en"}, client, device}` -> `data.token`.
  Token cached in `data/token.json`; 401 -> re-login once. Basic login works without MFA (confirmed).
- `GET /courses` -> `data[]` (`id`, `name`, `isInPersonalStudyPlan`, ...).
- `GET /courses/{id}/files` -> tree of `{type: directory|file}`; files have `id`, `name`, `mimeType`,
  `sizeInKiloBytes`, `createdAt`, `checksum`.
- `GET /courses/{id}/files/{fileId}` -> 302 redirect to the file (token only sent to the API host).
- `GET /courses/{id}/notices` -> `data[]` of `{id, publishedAt, expiresAt|null, content (HTML)}`. No title field.
  (Note: the spec lives on the `master` branch of polito/api-spec, not `main`.)

## Notices + Upcoming tabs
- `fetch_notices()` reads all study-plan courses' notices, converts HTML to text, caches them in
  `data/notices.json` (with a `seen` list: notices not seen before get `new: True`; the first fetch is a baseline).
- `extract_events()` is the offline "assistant": finds dates (EN/IT, numeric and month names, no-year
  dates roll forward), times and a kind (Seminar / talk, Exam, Deadline, Class change, Lab) per sentence;
  undated important notices from the last 14 days become "heads-up". Works with no API key.
- `ai_summary()` is optional: Claude (`claude-opus-5-5`) writes a digest if `anthropic` is installed and
  `ANTHROPIC_API_KEY` is in `.env` (Settings has the field). Not a required dependency.

## Sync rules (keep these; the user relies on them)
- Course -> local folder: `course_map.json` override, else loose name match (`norm()`: lowercase,
  alphanumerics only) against folders in `POLITO_DOWNLOAD_DIR`; unmatched -> skipped with a warning,
  unless `POLITO_CREATE_MISSING_COURSE_FOLDERS=1`.
- Files already anywhere in the course folder (name match via `file_key()`, ignores `[1]`/`(2)`) are
  recorded as present, not downloaded.
- New files go to `<course>/New/<portal subfolders>/`. Never move, modify or delete the user's files.
- `data/state.json` remembers each `courseId/fileId` + checksum; changed checksum -> re-download.
- Videos/audio and files > 200 MB skipped by default.

## Conventions
- `.env`, `data/`, `.venv/` are git-ignored. Never commit credentials or personal paths
  (repo may be public). Personal machine notes go in `CLAUDE.local.md` (git-ignored).
- Batch files need CRLF line endings.
- Run the tests after changing `polito_sync.py`; keep the GUI working without a console (pythonw).
