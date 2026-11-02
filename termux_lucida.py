"""Termux-first, browser-free Lucida HTTP CLI. Python 3.10+, json5 only."""
from __future__ import annotations

import argparse
import base64
import email.message
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

__version__ = "0.1.0"
ROOT = "https://lucida.to"
UA = os.environ.get("LUCIDA_USER_AGENT", "Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 Chrome/131.0.0.0 Mobile Safari/537.36")
DEFAULT_OUTPUT = Path(os.environ.get("LUCIDA_MUSIC_DIR", "~/storage/music" if Path("~/storage/music").expanduser().is_dir() else "~/Music")).expanduser()
DATA_START = ',{"type":"data","data":'
DATA_END = ',"uses":{"url":1}}];'
FORMATS = ("original", "flac", "mp3", "ogg-vorbis", "opus", "m4a-aac", "wav")
MIMES = {"audio/flac": ".flac", "audio/x-flac": ".flac", "audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/mp4": ".m4a", "audio/aac": ".aac", "audio/ogg": ".ogg", "audio/opus": ".opus", "audio/wav": ".wav", "audio/x-wav": ".wav", "application/zip": ".zip"}
MEDIA_EXTS = {".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".zip", ".aiff", ".alac"}
COUNTRIES = {"qobuz": "NL", "amazon": "", "grilledcheese": "", "deezer": "FR"}
SERVICES = ("amazon", "qobuz", "grilledcheese", "deezer", "tidal", "soundcloud")


class LucidaError(Exception):
    """Expected network, protocol, or filesystem failure."""


def safe_name(value: str, fallback: str = "Unknown") -> str:
    value = re.sub(r'[\\/\x00-\x1f\x7f<>:"|?*]', "_", str(value or ""))
    value = re.sub(r"\s+", " ", value).strip(" .")
    return (value[:145].rstrip(" .") or fallback)


def service_url(value: str) -> bool:
    parsed = urlsplit(value)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443):
        return False
    return host in ("open.qobuz.com", "play.qobuz.com", "tidal.com", "listen.tidal.com", "www.tidal.com", "soundcloud.com", "www.soundcloud.com", "www.deezer.com", "deezer.com", "open.spotify.com", "music.apple.com") or (host.startswith("music.amazon.") and len(host.split(".")) >= 3)


def normalize_service(value: str) -> str:
    return {"amazon_music": "amazon", "yandex_music": "yandex"}.get(value, value)


def parse_page(raw: str):
    """Parse SvelteKit JSON5 payload; fail closed when website markup changes."""
    start = raw.find(DATA_START)
    if start == -1:
        raise LucidaError("Lucida page data not found. The site may have changed or a browser verification is required.")
    start += len(DATA_START)
    end = raw.find(DATA_END, start)
    if end < 0:
        raise LucidaError("Lucida page data terminator not found (upstream layout changed).")
    try:
        import json5  # pure-Python package, not Playwright/Chromium
        return json5.loads(raw[start:end])
    except (ValueError, ImportError) as exc:
        raise LucidaError(f"Could not decode Lucida JSON5 data: {exc}") from exc


def find_results(value, depth=0):
    if depth > 10:
        return None
    if isinstance(value, dict):
        if any(isinstance(value.get(k), list) for k in ("tracks", "albums")):
            return value
        for item in value.values():
            found = find_results(item, depth + 1)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value:
            found = find_results(item, depth + 1)
            if found is not None:
                return found
    return None


def search_items(payload, kind="tracks"):
    root = find_results(payload) or {}
    result = []
    for item in root.get(kind, []) or []:
        if not isinstance(item, dict) or not isinstance(item.get("url"), str):
            continue
        artists = item.get("artists") or []
        artist = ", ".join(a.get("name", "") for a in artists if isinstance(a, dict) and a.get("name"))
        album = item.get("album") or {}
        result.append({"title": item.get("title") or "", "artist": artist, "album": album.get("title", "") if isinstance(album, dict) else "", "url": item["url"]})
    return result


def single_token(value):
    if not isinstance(value, str):
        return value
    result = value
    try:
        for _ in range(2):
            result = base64.b64decode(result, validate=True).decode("utf-8")
    except (UnicodeError, ValueError):
        return value
    return result


def tracks_from_page(page):
    if not isinstance(page, dict) or not isinstance(page.get("info"), dict):
        raise LucidaError("No usable track metadata returned by Lucida.")
    if page.get("tokenExpiry") is None:
        raise LucidaError("Lucida did not return a download token expiry.")
    info = page["info"]
    if info.get("type") == "album":
        tracks = info.get("tracks") or []
    else:
        one = dict(info)
        one.setdefault("csrf", single_token(page.get("token")))
        one.setdefault("csrfFallback", None)
        tracks = [one]
    tracks = [t for t in tracks if isinstance(t, dict) and isinstance(t.get("url"), str) and t.get("csrf")]
    if not tracks:
        raise LucidaError("No downloadable tracks or valid Lucida tokens were returned.")
    return tracks, page["tokenExpiry"], info


def safe_worker(server: str, handoff: str) -> str:
    if not isinstance(server, str) or not re.fullmatch(r"[a-zA-Z0-9-]{1,63}", server) or server.startswith("-") or server.endswith("-"):
        raise LucidaError("Unsafe or malformed download server received.")
    if not isinstance(handoff, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,256}", handoff):
        raise LucidaError("Unsafe or malformed handoff ID received.")
    return f"https://{server}.lucida.to/api/fetch/request/{handoff}"


class HTTPSOnlyRedirect(HTTPRedirectHandler):
    """Never follow a redirect that downgrades a download to plaintext HTTP."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme != "https":
            raise LucidaError("Refusing non-HTTPS redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Client:
    def __init__(self, base=ROOT, timeout=35.0, cookie=None, user_agent=UA):
        if base != ROOT:  # prevent passing tokens to arbitrary third-party origins
            raise LucidaError("Only the official lucida.to origin is accepted.")
        self.base = base
        self.timeout = timeout
        self.cookie = cookie if cookie is not None else os.environ.get("LUCIDA_COOKIE", "")
        self.user_agent = user_agent
        self.opener = build_opener(HTTPSOnlyRedirect())
        self.last_request = 0.0

    def request(self, method, url, data=None, stream=False, attempts=3):
        headers = {"User-Agent": self.user_agent, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.8"}
        if data is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(data, separators=(",", ":")).encode("utf-8")
        for attempt in range(attempts):
            delay = max(0, 0.75 - (time.monotonic() - self.last_request))
            if delay:
                time.sleep(delay)
            self.last_request = time.monotonic()
            try:
                request = Request(url, data=data, method=method, headers=headers)
                if self.cookie and urlsplit(url).hostname == "lucida.to":
                    # Unredirected header: never forward session credentials to a CDN or other origin.
                    request.add_unredirected_header("Cookie", self.cookie)
                response = self.opener.open(request, timeout=self.timeout)
                if stream:
                    return response
                with response:
                    raw = response.read(10 * 1024 * 1024 + 1)
                    if len(raw) > 10 * 1024 * 1024:
                        raise LucidaError("Lucida response exceeded 10 MiB; refusing unbounded page data.")
                    return raw.decode("utf-8", errors="replace")
            except HTTPError as exc:
                status = exc.code
                if status == 403:
                    raise LucidaError("HTTP 403 from Lucida: access denied or browser verification required. See README authentication notes.") from exc
                if status not in (429, 500, 502, 503, 504) or attempt + 1 >= attempts:
                    raise LucidaError(f"HTTP {status} from {urlsplit(url).hostname}") from exc
                retry_after = exc.headers.get("Retry-After", "")
                try:
                    wait = max(1, min(30, int(retry_after)))
                except ValueError:
                    wait = min(8, 2 ** attempt)
                time.sleep(wait)
            except (URLError, OSError, TimeoutError) as exc:
                if attempt + 1 >= attempts:
                    raise LucidaError(f"Network failure: {exc}") from exc
                time.sleep(min(8, 2 ** attempt))
        raise LucidaError("Request exhausted retries")

    def search(self, query: str, service="amazon", kind="tracks"):
        service = normalize_service(service)
        params = {"service": service, "query": query}
        if COUNTRIES.get(service):
            params["country"] = COUNTRIES[service]
        return search_items(parse_page(self.request("GET", self.base + "/search?" + urlencode(params))), kind)

    def resolve(self, url: str, country=None):
        if not service_url(url):
            raise LucidaError("Use a supported HTTPS music-service track or album URL, not an arbitrary address.")
        params = {"url": url}
        if country:
            params["country"] = country
        return parse_page(self.request("GET", self.base + "/?" + urlencode(params)))

    def start(self, track, expiry, fmt="original", country=""):
        data = {"account": {"id": country or "auto", "type": "country"}, "compat": False,
                "downscale": fmt, "handoff": True, "metadata": True, "private": False,
                "token": {"expiry": expiry, "primary": track.get("csrf"), "secondary": track.get("csrfFallback")},
                "upload": {"enabled": False}, "url": track["url"]}
        response = self.request("POST", self.base + "/api/load?" + urlencode({"url": "/api/fetch/stream/v2"}), data)
        try:
            payload = json.loads(response)
        except ValueError as exc:
            raise LucidaError("Lucida returned a non-JSON handoff response.") from exc
        if not isinstance(payload, dict) or not payload.get("server") or not payload.get("handoff"):
            detail = payload.get("error", payload) if isinstance(payload, dict) else payload
            raise LucidaError(f"Lucida did not accept this track: {str(detail)[:220]}")
        return safe_worker(payload["server"], payload["handoff"])

    def poll(self, job_url: str, deadline=600):
        stop = time.monotonic() + deadline
        last_status = None
        while time.monotonic() < stop:
            raw = self.request("GET", job_url)
            try:
                data = json.loads(raw)
            except ValueError as exc:
                raise LucidaError("Lucida worker returned invalid JSON.") from exc
            if not isinstance(data, dict):
                raise LucidaError("Lucida worker returned unexpected JSON data.")
            status = data.get("status", "")
            if status == "completed":
                return
            if status in ("error", "failed", "cancelled"):
                raise LucidaError("Lucida worker failed: " + str(data.get("message", status))[:220])
            label = str(data.get("message") or status)
            if label and label != last_status:
                print("  " + label[:110], file=sys.stderr)
                last_status = label
            time.sleep(1.5)
        raise LucidaError("Lucida processing timed out")

    def download(self, job_url: str, target_dir: Path, fallback: str) -> Path:
        target_dir.mkdir(parents=True, exist_ok=True)
        with self.request("GET", job_url + "/download", stream=True) as response:
            mime = response.headers.get_content_type().lower()
            if mime in ("text/html", "text/plain", "application/json"):
                raise LucidaError(f"Worker returned {mime}, not an audio file")
            ext = MIMES.get(mime, ".bin")
            cd = response.headers.get("Content-Disposition", "")
            message = email.message.Message()
            message["Content-Disposition"] = cd
            candidate = message.get_filename() or fallback
            # An unrecognized extension is not an audio type; preserve known ext only.
            name = safe_name(candidate)
            if Path(name).suffix.lower() not in MEDIA_EXTS:
                name += ext
            path = target_dir / name
            if path.exists():
                print(f"  exists, skipping: {path}")
                return path
            part = target_dir / (name + ".part")
            size = response.headers.get("Content-Length")
            expected = int(size) if size and size.isdecimal() else None
            total = 0
            try:
                with part.open("wb") as output:
                    while True:
                        chunk = response.read(65536)
                        if not chunk:
                            break
                        total += len(chunk)
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                if not total or (expected is not None and total != expected):
                    raise LucidaError(f"Truncated file: {total} bytes (expected {expected})")
                # Do not overwrite a preexisting filename.
                if path.exists():
                    raise LucidaError(f"Destination already exists: {path}")
                part.replace(path)
            except BaseException:
                part.unlink(missing_ok=True)
                raise
            print(f"  saved {total:,} bytes: {path}")
            return path


def label_track(t, info, index=1):
    artists = t.get("artists") or info.get("artists") or []
    artist = ", ".join(a.get("name", "") for a in artists if isinstance(a, dict) and a.get("name")) or "Unknown Artist"
    title = str(t.get("title") or info.get("title") or f"Track {index}")
    album = t.get("album") or {}
    album_name = album.get("title", "") if isinstance(album, dict) else str(album or "")
    if info.get("type") == "album" and not album_name:
        album_name = str(info.get("title") or "Unknown Album")
    return artist, album_name, title


def resolve_input(client, value: str, service: str, kind: str, pick: int | None):
    if service_url(value):
        return value
    if value.startswith("http:") or value.startswith("https:"):
        raise LucidaError("Unsupported URL. Only recognized HTTPS music-service URLs are allowed.")
    if pick is None:
        raise LucidaError("Search terms need --pick N. Run the search command first to select an exact match.")
    results = client.search(value, service=service, kind=kind)
    if not 1 <= pick <= len(results):
        raise LucidaError(f"Result {pick} unavailable; search returned {len(results)} results.")
    choice = results[pick - 1]
    print(f"  selected: {choice['artist']} - {choice['title']}")
    return choice["url"]


def download_input(client, value, args):
    url = resolve_input(client, value, args.service, "albums" if args.album else "tracks", args.pick)
    host = (urlsplit(url).hostname or "").lower()
    country = args.country or ("NL" if "qobuz.com" in host else "")
    page = client.resolve(url, country)
    tracks, expiry, info = tracks_from_page(page)
    out = Path(args.output).expanduser()
    total = len(tracks)
    ok = 0
    for i, track in enumerate(tracks, 1):
        artist, album, title = label_track(track, info, i)
        dest = out if args.flat else out / safe_name(artist) / safe_name(album or "Singles")
        if args.album or total > 1:
            title = f"{i:02d} - {title}"
        print(f"[{i}/{total}] {artist} - {title}")
        try:
            job = client.start(track, expiry, args.format, country)
            client.poll(job, deadline=args.timeout)
            client.download(job, dest, safe_name(title))
            ok += 1
        except (LucidaError, OSError) as exc:
            print(f"  FAILED: {exc}", file=sys.stderr)
    print(f"Completed: {ok}/{total} tracks")
    return ok == total


def doctor(client, live=False):
    import importlib.util
    print(f"Termux Lucida CLI {__version__}; Python {sys.version.split()[0]}")
    print(f"Termux environment: {'yes' if os.environ.get('PREFIX', '').startswith('/data/data/com.termux') else 'not detected (desktop testing is supported)'}")
    print(f"JSON5 parser: {'installed' if importlib.util.find_spec('json5') else 'MISSING: python -m pip install json5'}")
    print(f"Output folder: {DEFAULT_OUTPUT}")
    print(f"Android shared storage linked: {Path('~/storage').expanduser().is_dir()}")
    print(f"ffmpeg (optional): {shutil.which('ffmpeg') or 'not installed'}")
    print(f"Lucida session cookie configured: {'yes' if client.cookie else 'no'}")
    if live:
        raw = client.request("GET", ROOT + "/")
        print(f"Lucida response: {len(raw)} characters; SvelteKit payload {'detected' if DATA_START in raw else 'not detected'}")
        if "Just a moment" in raw or "cf-chl" in raw:
            raise LucidaError("A Cloudflare browser verification page was returned.")


def build_parser():
    p = argparse.ArgumentParser(prog="termux-lucida", description="Termux-native Lucida HTTP client (no Chromium, no Playwright)")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--http-timeout", type=float, default=35, help="Per HTTP request timeout in seconds")
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("search", help="Search Lucida and display source URLs")
    s.add_argument("query")
    s.add_argument("--service", choices=SERVICES, default="amazon")
    s.add_argument("--albums", action="store_true")
    s.add_argument("--limit", type=int, default=10)
    inf = sub.add_parser("info", help="Resolve a music URL and inspect its tracks")
    inf.add_argument("url")
    inf.add_argument("--country", default="")
    def common(cmd):
        cmd.add_argument("--service", choices=SERVICES, default="amazon")
        cmd.add_argument("--album", action="store_true", help="Search album results instead of tracks")
        cmd.add_argument("--pick", type=int, default=None, help="Explicit 1-based result to use for a text query")
        cmd.add_argument("--output", "-o", default=str(DEFAULT_OUTPUT), help="Destination folder")
        cmd.add_argument("--flat", action="store_true", help="No Artist/Album subfolders")
        cmd.add_argument("--format", choices=FORMATS, default="original", help="Lucida requested output format")
        cmd.add_argument("--country", default="", help="Provider region, e.g. NL or US; default auto")
        cmd.add_argument("--timeout", type=int, default=600, help="Max wait time per processing job")
    d = sub.add_parser("download", help="Download one track/album URL or an explicitly selected search result")
    d.add_argument("item")
    common(d)
    b = sub.add_parser("batch", help="Download URL lines from a UTF-8 text file")
    b.add_argument("file", type=Path)
    common(b)
    sub.add_parser("services", help="List supported Lucida search provider names")
    doc = sub.add_parser("doctor", help="Check Termux compatibility and optional live connectivity")
    doc.add_argument("--live", action="store_true")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if not 0 < args.http_timeout <= 300:
            raise LucidaError("--http-timeout must be between 0 and 300")
        client = Client(timeout=args.http_timeout)
        if args.command == "services":
            print("Search providers (actual upstream availability varies): " + ", ".join(SERVICES))
        elif args.command == "doctor":
            doctor(client, args.live)
        elif args.command == "search":
            kind = "albums" if args.albums else "tracks"
            results = client.search(args.query, args.service, kind)
            for n, item in enumerate(results[:max(0, args.limit)], 1):
                print(f"{n:>2}. {item['artist']} - {item['title']}\n    {item['url']}")
            print(f"Found {len(results)} {kind} (showing {min(len(results), max(0, args.limit))})")
        elif args.command == "info":
            host = (urlsplit(args.url).hostname or "").lower()
            cc = args.country or ("NL" if "qobuz.com" in host else "")
            tracks, expiry, info = tracks_from_page(client.resolve(args.url, cc))
            print(json.dumps({"type": info.get("type"), "title": info.get("title"), "tracks": [{"url": t["url"], "title": t.get("title")} for t in tracks], "count": len(tracks)}, indent=2, ensure_ascii=False))
        else:
            if args.timeout <= 0:
                raise LucidaError("--timeout must be positive")
            if args.command == "download":
                success = download_input(client, args.item, args)
            else:
                lines = [line.strip() for line in args.file.read_text(encoding="utf-8").splitlines()]
                lines = [line for line in lines if line and not line.startswith("#")]
                if not lines:
                    raise LucidaError("Batch file contains no URLs or queries")
                success = True
                for i, item in enumerate(lines, 1):
                    print(f"\nBatch {i}/{len(lines)}: {item}")
                    try:
                        if not download_input(client, item, args):
                            success = False
                    except (LucidaError, OSError) as exc:
                        print(f"  FAILED: {exc}", file=sys.stderr)
                        success = False
            return 0 if success else 1
        return 0
    except (LucidaError, OSError, ValueError) as exc:
        print("Error: " + str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
