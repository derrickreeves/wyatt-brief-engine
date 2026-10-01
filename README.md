# wyatt-brief-engine

Turns the Wyatt Portfolio Brief data into the PDF. n8n POSTs the pulls to `/render`; this returns the PDF (base64), markdown, flags and the payload. No schedule, no credentials, no storage.

Deployed through Coolify (Dockerfile build pack, port 8080). Every push to `main` redeploys.

## API
- `GET /health`
- `POST /render` JSON `{ "as_of": "YYYY-MM-DD", "pulls": { "<name>": {...} } }`

## Pulls the engine expects
See the header of `renderer/build_brief.py`. `kcm_flips` (KCM base, Flips table) is optional: when present, the KCM card gains the FLIPS block (added 2026-10-01).
