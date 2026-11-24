from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import re
import socket
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

logger = logging.getLogger('subdown')

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
TEMP_ROOT = Path(os.getenv("SUBDOWN_TEMP_DIR", tempfile.gettempdir())) / "subdown"
TEMP_ROOT.mkdir(parents=True, exist_ok=True)

MAX_URL_LENGTH = 2048
MAX_FILE_AGE_SECONDS = int(os.getenv("FILE_TTL_SECONDS", "900"))
MAX_CONCURRENT_JOBS = int(os.getenv("MAX_CONCURRENT_JOBS", "3"))
MAX_REQUESTS_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "20"))
semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)
request_log: dict[str, list[float]] = {}

app = FastAPI(title="SubDown API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

class InspectRequest(BaseModel):
    url: str = Field(min_length=8, max_length=MAX_URL_LENGTH)

class DownloadRequest(BaseModel):
    url: str = Field(min_length=8, max_length=MAX_URL_LENGTH)
    language: str = Field(min_length=1, max_length=40)
    kind: str = Field(default="manual", pattern="^(manual|automatic)$")
    format: str = Field(default="srt", pattern="^(srt|vtt|txt|raw)$")

def rate_limit(request: Request):
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    hits = [t for t in request_log.get(ip, []) if now - t < 60]
    if len(hits) >= MAX_REQUESTS_PER_MINUTE:
        raise HTTPException(429, "Too many requests. Please wait a minute.")
    hits.append(now)
    request_log[ip] = hits

def validate_public_url(raw: str) -> str:
    """Basic SSRF guard; production also needs outbound network restrictions."""
    if len(raw) > MAX_URL_LENGTH:
        raise HTTPException(400, "URL is too long.")
    parsed = urlparse(raw.strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise HTTPException(400, "Please enter a valid http:// or https:// video URL.")
    if parsed.username or parsed.password:
        raise HTTPException(400, "URLs containing credentials are not allowed.")
    host = parsed.hostname.lower().rstrip(".")
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise HTTPException(400, "Private or local URLs are not allowed.")
    try:
        addresses = socket.getaddrinfo(host, None)
        for item in addresses:
            ip = ipaddress.ip_address(item[4][0])
            if not ip.is_global:
                raise HTTPException(400, "Private or local network addresses are not allowed.")
    except socket.gaierror:
        pass
    return raw.strip()

def ydl_options(extra: dict | None = None) -> dict:
    opts = {
        "quiet": True, "no_warnings": True, "skip_download": True,
        "noplaylist": True, "socket_timeout": 15, "retries": 1,
        "extractor_retries": 1, "cachedir": False,
    }
    provider_url = os.getenv("YTDL_POT_PROVIDER_URL", "").strip()
    if provider_url:
        opts["extractor_args"] = {
            "youtubepot-bgutilhttp": {"base_url": provider_url}
        }
    if extra:
        opts.update(extra)
    return opts

def language_rows(captions: dict) -> list[dict]:
    rows = []
    for code, tracks in captions.items():
        if not isinstance(tracks, list) or not tracks:
            continue
        usable = [t for t in tracks if isinstance(t, dict) and t.get("url")]
        if not usable:
            continue
        usable.sort(key=lambda t: (0 if t.get("ext") in ("vtt", "srt", "ttml", "json3") else 1))
        track = usable[0]
        rows.append({"code": str(code)[:40], "name": str(track.get("name") or code)[:100],
                     "ext": str(track.get("ext") or "unknown")[:20]})
    return sorted(rows, key=lambda x: x["name"].lower())

def extract_metadata(url: str) -> dict:
    with yt_dlp.YoutubeDL(ydl_options()) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info:
        raise ValueError("No video information was returned.")
    return {
        "id": str(info.get("id") or ""),
        "title": str(info.get("title") or "Untitled video")[:300],
        "thumbnail": info.get("thumbnail") if str(info.get("thumbnail") or "").startswith("https://") else None,
        "duration": info.get("duration"),
        "uploader": str(info.get("uploader") or info.get("channel") or "")[:160],
        "extractor": str(info.get("extractor_key") or info.get("extractor") or "Supported source")[:100],
        "manual": language_rows(info.get("subtitles") or {}),
        "automatic": language_rows(info.get("automatic_captions") or {}),
    }

def clean_old_files():
    cutoff = time.time() - MAX_FILE_AGE_SECONDS
    for item in TEMP_ROOT.iterdir():
        try:
            if item.is_file() and item.stat().st_mtime < cutoff:
                item.unlink(missing_ok=True)
            elif item.is_dir() and item.stat().st_mtime < cutoff:
                for child in item.iterdir():
                    child.unlink(missing_ok=True)
                item.rmdir()
        except OSError:
            pass

def download_caption(url: str, language: str, kind: str, output_dir: Path) -> Path:
    opts = ydl_options({
        "writesubtitles": kind == "manual", "writeautomaticsub": kind == "automatic",
        "subtitleslangs": [language], "subtitlesformat": "vtt/best",
        "outtmpl": str(output_dir / "caption.%(ext)s"), "overwrites": True,
    })
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])
    candidates = [p for p in output_dir.iterdir() if p.is_file()]
    if not candidates:
        raise ValueError("The selected subtitle track could not be downloaded.")
    return candidates[0]

TIMESTAMP_RE = re.compile(r"^(\d{1,2}:)?\d{2}:\d{2}[.,]\d{3}\s+-->\s+")

def to_srt(source: str) -> str:
    text = source.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n")
    blocks = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.splitlines()
        if not lines:
            continue
        if lines[0].strip().isdigit():
            lines = lines[1:]
        if lines and TIMESTAMP_RE.match(lines[0].strip()):
            lines[0] = lines[0].replace(".", ",")
            blocks.append(lines)
    return "\n\n".join(f"{i}\n" + "\n".join(b) for i, b in enumerate(blocks, 1)) + ("\n" if blocks else "")

def to_txt(source: str) -> str:
    text = source.replace("\ufeff", "").replace("\r\n", "\n")
    output = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s == "WEBVTT" or s.startswith(("NOTE", "STYLE", "REGION")):
            continue
        if s.isdigit() or "-->" in s:
            continue
        output.append(re.sub(r"<[^>]+>", "", s))
    return "\n".join(output).strip() + "\n"

@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "SubDown"}

@app.post("/api/inspect")
async def inspect(payload: InspectRequest, request: Request):
    rate_limit(request)
    url = validate_public_url(payload.url)
    try:
        async with semaphore:
            data = await asyncio.wait_for(asyncio.to_thread(extract_metadata, url), timeout=90)
        if not data["manual"] and not data["automatic"]:
            raise HTTPException(404, "No subtitles or captions were found for this video.")
        return data
    except HTTPException:
        raise
    except asyncio.TimeoutError:
        raise HTTPException(504, "Subtitle detection timed out. Try again later.")
    except Exception as exc:
        logger.exception("Subtitle inspection failed for URL host %s", urlparse(url).hostname)
        message = str(exc).lower()
        if "sign in to confirm" in message or "not a bot" in message or "http error 403" in message:
            detail = "YouTube is blocking requests from this server right now. Please try again later."
        elif "javascript runtime" in message or "challenge solving" in message or "ejs" in message:
            detail = "YouTube verification setup is incomplete on the server. Please contact the site administrator."
        elif "private video" in message or "members-only" in message or "age" in message:
            detail = "This video requires access that SubDown cannot use. Try a public video."
        else:
            detail = "Could not read this video. The server log contains the technical error."
        raise HTTPException(422, detail) from exc

def cleanup_dir(path: Path):
    try:
        for child in path.iterdir():
            child.unlink(missing_ok=True)
        path.rmdir()
    except OSError:
        pass

@app.post("/api/download")
async def download(payload: DownloadRequest, request: Request):
    rate_limit(request)
    url = validate_public_url(payload.url)
    job_dir = TEMP_ROOT / uuid.uuid4().hex
    job_dir.mkdir(parents=True, exist_ok=False)
    try:
        async with semaphore:
            source_path = await asyncio.wait_for(
                asyncio.to_thread(download_caption, url, payload.language, payload.kind, job_dir), timeout=90)
        raw = source_path.read_text(encoding="utf-8", errors="replace")
        fmt = payload.format
        if fmt == "raw":
            content, suffix, media = raw, source_path.suffix.lstrip(".") or "txt", "text/plain; charset=utf-8"
        elif fmt == "vtt":
            if raw.lstrip().startswith("WEBVTT"):
                content = raw
            else:
                content = "WEBVTT\n\n" + to_srt(raw).replace(",", ".")
            suffix, media = "vtt", "text/vtt; charset=utf-8"
        elif fmt == "srt":
            content, suffix, media = to_srt(raw), "srt", "application/x-subrip; charset=utf-8"
        else:
            content, suffix, media = to_txt(raw), "txt", "text/plain; charset=utf-8"
        output = job_dir / f"subtitle.{suffix}"
        output.write_text(content, encoding="utf-8")
        return FileResponse(output, media_type=media, filename=f"subtitle-{payload.language}.{suffix}",
                            background=BackgroundTask(lambda: cleanup_dir(job_dir)))
    except asyncio.TimeoutError:
        cleanup_dir(job_dir)
        raise HTTPException(504, "Subtitle download timed out.")
    except Exception as exc:
        cleanup_dir(job_dir)
        raise HTTPException(422, "Could not download that subtitle track. It may have expired or be unavailable.") from exc

@app.on_event("startup")
async def startup_cleanup():
    clean_old_files()

app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
