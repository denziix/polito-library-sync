#!/usr/bin/env python3
"""polito-library-sync: download new course files from the PoliTO teaching portal.

Uses the official PoliTO Students API (https://github.com/polito/api-spec).
Run it on a schedule; it only downloads files it has not seen before
(or whose checksum changed).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urljoin, urlparse

import requests

API = "https://app.didattica.polito.it/api"
HERE = Path(__file__).resolve().parent
log = logging.getLogger("polito_sync")


class AuthError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
def load_env(path: Path) -> None:
    """Minimal .env loader (KEY=VALUE lines). Real env vars win."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


class Config:
    def __init__(self) -> None:
        load_env(HERE / ".env")
        self.username = os.environ.get("POLITO_USERNAME", "")
        self.password = os.environ.get("POLITO_PASSWORD", "")
        default_dir = Path.home() / "Documents" / "Polito"
        self.download_dir = Path(os.environ.get("POLITO_DOWNLOAD_DIR", default_dir)).expanduser()
        self.state_dir = Path(os.environ.get("POLITO_STATE_DIR", HERE / "data")).expanduser()
        # Videolectures are huge: skipped by default. Set POLITO_SKIP_MIME= (empty) to get them.
        skip = os.environ.get("POLITO_SKIP_MIME", "video/,audio/")
        self.skip_mime = tuple(p.strip() for p in skip.split(",") if p.strip())
        self.max_size_mb = float(os.environ.get("POLITO_MAX_SIZE_MB", "200"))
        self.only_study_plan = os.environ.get("POLITO_ONLY_STUDY_PLAN", "1") != "0"

    def validate(self) -> None:
        if not self.username or not self.password:
            raise AuthError("Set POLITO_USERNAME and POLITO_PASSWORD in .env (see .env.example).")


# --------------------------------------------------------------------------
# API client
# --------------------------------------------------------------------------
class PolitoApi:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.session = requests.Session()
        self.token_file = cfg.state_dir / "token.json"
        self.token: str | None = self._load_token()

    # -- token cache --------------------------------------------------------
    def _load_token(self) -> str | None:
        try:
            data = json.loads(self.token_file.read_text(encoding="utf-8"))
            if data.get("username") == self.cfg.username:
                return data.get("token")
        except (OSError, ValueError):
            pass
        return None

    def _save_token(self) -> None:
        self.cfg.state_dir.mkdir(parents=True, exist_ok=True)
        self.token_file.write_text(
            json.dumps({"username": self.cfg.username, "token": self.token}), encoding="utf-8"
        )
        try:
            os.chmod(self.token_file, 0o600)
        except OSError:
            pass

    def _drop_token(self) -> None:
        self.token = None
        try:
            self.token_file.unlink()
        except OSError:
            pass

    # -- login ----------------------------------------------------------------
    def login(self) -> None:
        self.cfg.validate()
        body = {
            "loginType": "basic",
            "username": self.cfg.username,
            "password": self.cfg.password,
            "preferences": {"language": "en"},
            "client": {"name": "polito-library-sync", "appVersion": "0.1.0", "buildNumber": "1"},
            "device": {"platform": sys.platform, "name": "polito-library-sync", "toothPicCompatible": False},
        }
        r = self.session.post(f"{API}/auth/login", json=body, timeout=30)
        if r.status_code != 200:
            raise AuthError(
                f"Login failed (HTTP {r.status_code}). Check your credentials. "
                "If they are right, the account may require MFA for this login type."
            )
        self.token = r.json()["data"]["token"]
        self._save_token()
        log.info("Logged in.")

    # -- requests -------------------------------------------------------------
    def _request(self, method: str, path: str, **kw: Any) -> requests.Response:
        for attempt in (1, 2):
            if not self.token:
                self.login()
            r = self.session.request(
                method,
                f"{API}{path}",
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=30,
                allow_redirects=False,
                **kw,
            )
            if r.status_code == 401 and attempt == 1:
                self._drop_token()
                continue
            return r
        raise AuthError("Authentication failed repeatedly.")

    def courses(self) -> list[dict[str, Any]]:
        r = self._request("GET", "/courses")
        r.raise_for_status()
        return r.json()["data"]

    def files(self, course_id: int) -> list[dict[str, Any]]:
        r = self._request("GET", f"/courses/{course_id}/files")
        r.raise_for_status()
        return r.json()["data"]

    def download(self, course_id: int, file_id: str, dest: Path) -> None:
        r = self._request("GET", f"/courses/{course_id}/files/{file_id}", stream=True)
        if r.status_code in (301, 302, 303, 307, 308):
            target = urljoin(r.url, r.headers["Location"])
            # Only send the token to the PoliTO API host, never to a third party.
            headers = {}
            if urlparse(target).netloc == urlparse(API).netloc:
                headers["Authorization"] = f"Bearer {self.token}"
            r.close()
            r = self.session.get(target, headers=headers, stream=True, timeout=60)
        r.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        with part.open("wb") as fh:
            for chunk in r.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
        os.replace(part, dest)


# --------------------------------------------------------------------------
# Sync logic
# --------------------------------------------------------------------------
_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_name(name: str) -> str:
    cleaned = _BAD.sub("_", name).strip(" .")
    return cleaned[:150] or "unnamed"


def walk(entries: list[dict[str, Any]], parts: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], dict[str, Any]]]:
    """Yield (directory parts, file entry) for every file in a course tree."""
    for e in entries:
        if e.get("type") == "directory":
            yield from walk(e.get("files", []), parts + (safe_name(e["name"]),))
        elif e.get("type") == "file":
            yield parts, e


def skip_reason(f: dict[str, Any], cfg: Config) -> str | None:
    mime = f.get("mimeType", "")
    if any(mime.startswith(p) for p in cfg.skip_mime):
        return f"mime {mime}"
    size_mb = f.get("sizeInKiloBytes", 0) / 1024
    if cfg.max_size_mb and size_mb > cfg.max_size_mb:
        return f"{size_mb:.0f} MB > limit"
    return None


def load_state(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"files": {}}


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def sync(api: PolitoApi, cfg: Config, init_only: bool = False, dry_run: bool = False) -> list[Path]:
    state_path = cfg.state_dir / "state.json"
    state = load_state(state_path)
    known: dict[str, Any] = state.setdefault("files", {})
    new_files: list[Path] = []

    for course in api.courses():
        if cfg.only_study_plan and not course.get("isInPersonalStudyPlan", True):
            continue
        cname = safe_name(course.get("name", str(course["id"])))
        try:
            tree = api.files(course["id"])
        except requests.RequestException as exc:
            log.warning("Could not list files for %s: %s", cname, exc)
            continue
        for parts, f in walk(tree):
            key = f"{course['id']}/{f['id']}"
            if known.get(key, {}).get("checksum") == f.get("checksum"):
                continue
            reason = skip_reason(f, cfg)
            if reason:
                log.debug("Skipping %s (%s)", f["name"], reason)
                continue
            dest = cfg.download_dir.joinpath(cname, *parts, safe_name(f["name"]))
            if init_only or dry_run:
                log.info("%s: %s", "Would record" if dry_run else "Recorded", dest)
            else:
                try:
                    api.download(course["id"], f["id"], dest)
                except requests.RequestException as exc:
                    log.warning("Download failed for %s: %s", dest, exc)
                    continue
                log.info("Downloaded %s", dest)
                new_files.append(dest)
            if not dry_run:
                known[key] = {
                    "checksum": f.get("checksum"),
                    "path": str(dest),
                    "seen_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                }
                save_state(state_path, state)  # persist progress after each file
    return new_files


def notify(files: list[Path]) -> None:
    """Optional Windows toast (pip install winotify). Silently skipped if missing."""
    if not files:
        return
    try:
        from winotify import Notification  # type: ignore

        Notification(
            app_id="polito-library-sync",
            title=f"{len(files)} new PoliTO file(s)",
            msg="\n".join(p.name for p in files[:5]),
        ).show()
    except Exception:  # noqa: BLE001 - notifications are best-effort
        pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--init-only", action="store_true", help="record current files as seen, download nothing")
    ap.add_argument("--dry-run", action="store_true", help="show what would happen, change nothing")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    cfg = Config()
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(cfg.state_dir / "sync.log", encoding="utf-8")],
    )
    try:
        new = sync(PolitoApi(cfg), cfg, init_only=args.init_only, dry_run=args.dry_run)
    except AuthError as exc:
        log.error("%s", exc)
        return 2
    except requests.RequestException as exc:
        log.error("Network/API error: %s", exc)
        return 1
    notify(new)
    log.info("Done. %d new file(s).", len(new))
    return 0


if __name__ == "__main__":
    sys.exit(main())
