# StarterStack Image Proxy

Cloudflare Worker that serves images from a private R2 bucket with HMAC-signed URLs, on-the-fly resizing, and CDN caching.

## What it does

- Verifies HMAC signatures on incoming requests (prevents unauthorized access)
- Fetches files from the private `starterstack-os-files` R2 bucket via binding (zero network hop)
- Resizes images on-the-fly using Cloudflare Image Resizing (WebP thumbnails, previews)
- Caches at 300+ Cloudflare edge locations via `Cache-Control` headers
- CORS-enabled for allowed origins

## URL format

```
https://<worker-url>/<r2_key>?w=384&q=75&f=webp&exp=1738800000&sig=<hmac>
```

| Param | Description |
|-------|-------------|
| `w`   | Width in px (0 = original) |
| `q`   | Quality 1-100 |
| `f`   | Format: `webp`, `avif`, `auto` |
| `exp` | Expiration timestamp (day-window rounded) |
| `sig` | HMAC-SHA256 signature (first 32 hex chars) |

Signed URLs are deterministic within a day and valid for 7 days.

## Size variants

| Variant   | Width | Quality | Format |
|-----------|-------|---------|--------|
| `thumb`   | 384px | 75      | webp   |
| `chat`    | 768px | 82      | webp   |
| `preview` | 1200px| 85      | webp   |
| `full`    | original | 100  | auto   |

## Setup

### Prerequisites

- [Node.js](https://nodejs.org/) 18+
- [Wrangler](https://developers.cloudflare.com/workers/wrangler/) CLI (`npm install -g wrangler`)
- Cloudflare account with the `starterstack-os-files` R2 bucket

### Deploy

```bash
npm install
wrangler login
wrangler deploy
wrangler secret put IMAGE_PROXY_SECRET
```

After deploy, Wrangler prints your Worker URL (e.g. `https://core-image-proxy.<subdomain>.workers.dev`).

### Environment

**Worker secrets** (set via `wrangler secret put`):
- `IMAGE_PROXY_SECRET` — HMAC signing key (must match `core-api` env var)

**Worker vars** (in `wrangler.toml`):
- `ALLOWED_ORIGINS` — comma-separated list of allowed CORS origins
- `MAX_AGE` — CDN cache TTL in seconds (default: 86400)
- `BROWSER_MAX_AGE` — browser cache TTL in seconds (default: 86400)

### Backend config

Set these in `core-api` environment (Vercel):
- `IMAGE_PROXY_SECRET` — same value as the Worker secret
- `IMAGE_PROXY_URL` — the Worker URL from deploy output

When both are empty, the backend falls back to presigned R2 URLs automatically.

## Local development

```bash
wrangler dev
```

Starts a local Worker at `http://localhost:8787`.
