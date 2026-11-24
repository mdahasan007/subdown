# SubDown — Universal Video Subtitle Downloader

A responsive subtitle downloader built with FastAPI, yt-dlp and vanilla HTML/CSS/JavaScript. It detects manual and auto-generated caption tracks for URLs supported by the installed yt-dlp extractors. It does **not** download the video itself.

## Features

- Video metadata and thumbnail preview
- Manual and auto-generated caption track discovery
- SRT, VTT, TXT and RAW exports
- Responsive dark UI with light-mode toggle
- Basic URL validation, private-address checks, per-IP rate limiting
- Bounded concurrent extraction and temporary-file cleanup
- Docker deployment

## Requirements

- Python 3.11+
- ffmpeg (recommended; installed in the Docker image)
- Internet access from the backend

## Run locally

```bash
python -m venv .venv

# Windows:
.venv\\Scripts\\activate

# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000

## Run with Docker

```bash
docker compose up --build -d
```

Open http://localhost:8000

## API

### `POST /api/inspect`

```json
{"url":"https://www.youtube.com/watch?v=VIDEO_ID"}
```

Returns title, duration, uploader, thumbnail, manual subtitle tracks and automatic caption tracks.

### `POST /api/download`

```json
{
  "url":"https://www.youtube.com/watch?v=VIDEO_ID",
  "language":"en",
  "kind":"manual",
  "format":"srt"
}
```

- `kind`: `manual` or `automatic`
- `format`: `srt`, `vtt`, `txt`, `raw`

### `GET /api/health`

Health check.

## YouTube extraction support

The Docker image includes Deno, yt-dlp's JavaScript challenge components, and the community-maintained BgUtils PO Token provider plugin plus its local HTTP provider. The provider runs inside the same container on localhost:4416; the FastAPI service uses it automatically. This can improve YouTube compatibility when PO-token challenges are the cause, but **does not guarantee** access when YouTube blocks the hosting IP, rate-limits requests, or changes its checks. The provider is third-party software and is not affiliated with YouTube or yt-dlp. Never add browser cookies or account credentials to a public subtitle service.

## Platform coverage

yt-dlp supports a large and changing set of extractors. Actual caption availability depends on the source platform, the individual video, account/region restrictions, and the extractor version. A supported video URL does not guarantee subtitles exist. Some services require authentication or do not expose captions to anonymous requests. This project intentionally does not bypass DRM, paywalls, access controls, or private-video restrictions.

Keep yt-dlp updated:

```bash
pip install -U yt-dlp
```

## Important production security notes

This is a functional MVP, not a fully hardened public multi-tenant service.

1. **Outbound network isolation is mandatory.** The app performs basic DNS/IP checks, but DNS rebinding and redirects can defeat application-only SSRF checks. Run it behind an egress firewall/proxy that blocks loopback, RFC1918, link-local, metadata-service and other non-public destinations. Ideally allow only required public destinations.
2. Put the app behind HTTPS and a reverse proxy with request/body/time limits.
3. Replace in-memory rate limiting with Redis when running multiple workers/instances.
4. Add authentication/quotas if you expect sustained public usage.
5. Keep yt-dlp and the base image patched. Run as a non-root user (Dockerfile does).
6. Do not mount host secrets, browser profiles, or personal cookies into the extraction container.
7. Review the terms and copyright rules of each platform. Only download captions you are authorized to access and use.
8. For production, add a durable job queue (Celery/RQ + Redis) and a separate restricted worker container. The current MVP uses bounded in-process tasks.

## Project structure

```text
subdown/
├── app/
│   ├── main.py
│   └── static/
│       ├── index.html
│       ├── styles.css
│       └── app.js
├── .env.example
├── .gitignore
├── Dockerfile
├── compose.yaml
├── requirements.txt
└── README.md
```
