# PoliTO Sync (polito-library-sync)

Windows app that downloads new course files from the Politecnico di Torino teaching portal into
the user's own course folders. Shared with friends via GitHub (they use Download ZIP + Setup.bat).

## Files
- `polito_sync.py` - core: config (.env), API client, sync logic, CLI (`--dry-run`, `--init-only`, `-v`).
- `polito_gui.pyw` - tkinter app window: sidebar (Files / Notices / Upcoming, count badges, Settings,
  light/dark toggle) + pages. The sidebar collapses to a 68px icon rail (☰ button or Ctrl+B; badges become
  dots, hover shows a tooltip; remembered as `POLITO_SIDEBAR=open|collapsed` in `.env`). Sidebar and page
  (`self.main`) are both positioned with `place`: the slide only moves them (smooth, ~12ms frames), then
  the page changes width once in `_relayout()`, which pauses drawing (WM_SETREDRAW) so it appears in one go.
  Rounded cards / nav highlights use `_Canvas.round_rect()` (4 cached corner images + plain shapes), so
  resizing never renders new images. Runs sync in a thread and gets progress via `sync(..., progress=callback)`
  events: "courses", "course", "file". First launch opens a Settings dialog that writes `.env`
  (keeps other lines intact). Look: navy + seal blue (#495764) as main colours, crimson pink as the accent
  ("harbor" light / "deep navy" dark), no logo (just the "polito.sync" wordmark), Bahnschrift headings,
  lowercase casual copy. Custom canvas widgets: `PillButton` (gradient / ghost), `Chip`, `RoundCard`
  (content in `.inner`), `NavItem`, `Hero` banner, `Meter` progress, `Ripple`.
  `Ripple`: pixelated colour wave over the whole window when "sync now" (Files) or "refresh" (Notices) is
  clicked. A borderless, click-through overlay Toplevel (`-transparentcolor` key + `-alpha`, Windows only)
  with one canvas rectangle per lit block (28px blocks, ~1150 cells, at most ~260 lit); blocks are sorted by
  distance so a frame only visits blocks near each wave, and are reused (recoloured/hidden). Capped at
  ~30 fps (`FRAME_MS`), ~0.12s CPU per ripple. `POLITO_RIPPLE=0` in `.env` turns it off.
  Notices page: list card on top, reader card underneath (vertical PanedWindow). The list card has two
  views (`self.nview`): "subjects" = boxes in a 1-4 column grid by width (`_subject_box`, `_wrap_subjects`:
  "all" first, then courses by latest notice, with "N new" chips) and "list" = that subject's notices with a
  "‹ subjects" back button (course column hidden for a single course). Typing in search from the boxes
  switches to "all"; `open_notice()` (from Upcoming) opens the notice inside its course's list.
  List previews skip "Dear students,"-style greetings (`notice_preview()`).
  Sun Valley theme (`sv-ttk`) for stock ttk widgets. `PALETTES`/`KIND_COLORS`/`COURSE_COLORS` per mode,
  `POLITO_THEME=system|light|dark` in `.env`. Changing theme destroys and rebuilds the widgets
  (`set_theme`), so state that must survive lives on the App (`course_rows`, `log_lines`, notices, StringVars).
- `ui_gfx.py` - Pillow drawing (Tk can't anti-alias): rounded shapes, gradients, mesh-gradient hero
  (blobs placed in gradient order, so the last colour stays a splash on the right), colour emoji
  (Segoe UI Emoji). Cached with lru_cache; `clear_cache()` on theme change / new root.
  `sv-ttk` and `Pillow` are both optional at runtime: without them the UI falls back to flat shapes.
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
- With that option on (default for new installs via `.env.example` and the first-run Settings box),
  `create_course_folders()` makes one folder per study-plan course (`course_folder_name()`: "a/b" -> "a-b"),
  reusing matched folders: right after Settings is saved (GUI logs in, then shows what it made) and at
  the start of every real sync (not `--dry-run`), so courses without files still get a folder.
  The owner's own install has it off (own folder layout) - don't turn it on for them.
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
