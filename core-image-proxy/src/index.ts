/**
 * StarterStack Image Proxy Worker
 *
 * Serves files from a private R2 bucket with:
 * - HMAC-signed URL verification (Discord-style deterministic signatures)
 * - On-the-fly image resizing via Images binding (no custom domain needed)
 * - Two-layer caching: Cache API (per-colo, fast) + R2 variants (global, permanent)
 * - CORS for allowed origins
 */

interface Env {
	FILES_BUCKET: R2Bucket;
	IMAGES: ImagesBinding;
	IMAGE_PROXY_SECRET: string;
	ALLOWED_ORIGINS: string;
	MAX_AGE: string;
	BROWSER_MAX_AGE: string;
}

interface ImagesBinding {
	input(stream: ReadableStream): ImageTransformBuilder;
}

interface ImageTransformBuilder {
	transform(options: ImageTransformOptions): ImageTransformBuilder;
	output(options: ImageOutputOptions): Promise<ImageOutputResult>;
}

interface ImageTransformOptions {
	width?: number;
	height?: number;
	fit?: 'scale-down' | 'contain' | 'cover' | 'crop' | 'pad';
}

interface ImageOutputOptions {
	format: 'image/webp' | 'image/avif' | 'image/jpeg' | 'image/png';
	quality?: number;
}

interface ImageOutputResult {
	response(): Response;
}

const encoder = new TextEncoder();

/** Convert ArrayBuffer to hex string. */
function bufferToHex(buffer: ArrayBuffer): string {
	return [...new Uint8Array(buffer)]
		.map((b) => b.toString(16).padStart(2, '0'))
		.join('');
}

/** Timing-safe string comparison. */
function timingSafeEqual(a: string, b: string): boolean {
	if (a.length !== b.length) return false;
	const aBuf = encoder.encode(a);
	const bBuf = encoder.encode(b);
	let result = 0;
	for (let i = 0; i < aBuf.length; i++) {
		result |= aBuf[i] ^ bBuf[i];
	}
	return result === 0;
}

/** Verify HMAC signature for a request. */
async function verifySignature(
	r2Key: string,
	width: number,
	quality: number,
	format: string,
	exp: number,
	sig: string,
	secret: string,
): Promise<boolean> {
	const message = `${r2Key}:${width}:${quality}:${format}:${exp}`;
	const key = await crypto.subtle.importKey(
		'raw',
		encoder.encode(secret),
		{ name: 'HMAC', hash: 'SHA-256' },
		false,
		['sign'],
	);
	const signature = await crypto.subtle.sign('HMAC', key, encoder.encode(message));
	const computed = bufferToHex(signature).slice(0, 32);
	return timingSafeEqual(computed, sig);
}

/** Map format string to MIME type for Images binding output. */
function formatToMime(format: string, originalType: string): 'image/webp' | 'image/avif' | 'image/jpeg' | 'image/png' {
	switch (format) {
		case 'webp': return 'image/webp';
		case 'avif': return 'image/avif';
		default: return originalType as 'image/jpeg' | 'image/png';
	}
}

/** Get MIME type from format string without needing the original. Returns null for 'auto'. */
function mimeFromFormat(format: string): string | null {
	switch (format) {
		case 'webp': return 'image/webp';
		case 'avif': return 'image/avif';
		case 'jpeg': case 'jpg': return 'image/jpeg';
		case 'png': return 'image/png';
		default: return null;
	}
}

/** Check if a content type can be resized by the Images binding. */
function isResizableImage(contentType: string): boolean {
	const resizable = new Set(['image/jpeg', 'image/png', 'image/gif', 'image/webp']);
	return resizable.has(contentType);
}

/** Infer Content-Type from R2 key extension. */
function inferContentType(key: string): string {
	const ext = key.split('.').pop()?.toLowerCase();
	const map: Record<string, string> = {
		jpg: 'image/jpeg', jpeg: 'image/jpeg',
		png: 'image/png', gif: 'image/gif',
		webp: 'image/webp', heic: 'image/heic', heif: 'image/heif',
		pdf: 'application/pdf', mp4: 'video/mp4',
		mov: 'video/quicktime', webm: 'video/webm',
	};
	return map[ext || ''] || 'application/octet-stream';
}

/** Get allowed origin for CORS, or null if not allowed. */
function getAllowedOrigin(request: Request, env: Env): string | null {
	const origin = request.headers.get('Origin');
	if (!origin) return null;
	const allowed = env.ALLOWED_ORIGINS.split(',').map((o) => o.trim());
	return allowed.includes(origin) ? origin : null;
}

/** Normalize an ETag token for weak/strong comparison. */
function normalizeEtag(etag: string): string {
	return etag.trim().replace(/^W\//, '');
}

/** Check If-None-Match header against a candidate ETag. */
function etagMatches(ifNoneMatch: string | null, etag: string): boolean {
	if (!ifNoneMatch) return false;
	if (ifNoneMatch.trim() === '*') return true;
	const target = normalizeEtag(etag);
	return ifNoneMatch
		.split(',')
		.map((t) => t.trim())
		.some((t) => normalizeEtag(t) === target);
}

/** Build a deterministic ETag for transformed images. */
function buildTransformedEtag(objectEtag: string | undefined, width: number, quality: number, format: string): string {
	const base = (objectEtag || 'noetag').replace(/"/g, '');
	return `"img-${base}-${width}-${quality}-${format}"`;
}

/** Build R2 key for a cached transform variant. */
function buildVariantKey(r2Key: string, width: number, quality: number, format: string): string {
	return `_variants/${r2Key}/w${width}_q${quality}_${format}`;
}

export default {
	async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
		// Handle CORS preflight
		if (request.method === 'OPTIONS') {
			const origin = getAllowedOrigin(request, env);
			return new Response(null, {
				status: 204,
				headers: {
					...(origin && { 'Access-Control-Allow-Origin': origin }),
					'Access-Control-Allow-Methods': 'GET, HEAD, OPTIONS',
					'Access-Control-Allow-Headers': 'Content-Type',
					'Access-Control-Max-Age': '86400',
				},
			});
		}

		if (request.method !== 'GET' && request.method !== 'HEAD') {
			return new Response('Method not allowed', { status: 405 });
		}

		const url = new URL(request.url);

		// Parse R2 key from URL path (strip leading slash)
		const r2Key = decodeURIComponent(url.pathname.slice(1));
		if (!r2Key) {
			return new Response('Missing file path', { status: 400 });
		}

		// Parse query parameters
		const width = parseInt(url.searchParams.get('w') || '0', 10);
		const quality = parseInt(url.searchParams.get('q') || '85', 10);
		const format = url.searchParams.get('f') || 'auto';
		const exp = parseInt(url.searchParams.get('exp') || '0', 10);
		const sig = url.searchParams.get('sig') || '';

		// Validate required params
		if (!sig || !exp) {
			return new Response('Missing signature or expiration', { status: 403 });
		}

		// Check expiration
		const now = Math.floor(Date.now() / 1000);
		if (now > exp) {
			return new Response('URL expired', { status: 403 });
		}

		// Verify HMAC signature
		const valid = await verifySignature(r2Key, width, quality, format, exp, sig, env.IMAGE_PROXY_SECRET);
		if (!valid) {
			return new Response('Invalid signature', { status: 403 });
		}

		const origin = getAllowedOrigin(request, env);
		const maxAge = parseInt(env.MAX_AGE || '604800', 10);
		const browserMaxAge = parseInt(env.BROWSER_MAX_AGE || '604800', 10);
		const cacheControl = `public, max-age=${browserMaxAge}, s-maxage=${maxAge}, immutable`;

		// --- L1: Cache API (per-colo, ephemeral, ~1ms) ---
		const cache = caches.default;
		const cacheUrl = new URL(url.toString());
		cacheUrl.searchParams.delete('exp');
		cacheUrl.searchParams.delete('sig');
		const cacheKey = new Request(cacheUrl.toString());

		const cached = await cache.match(cacheKey);
		if (cached) {
			const resp = new Response(cached.body, cached);
			if (origin) {
				resp.headers.set('Access-Control-Allow-Origin', origin);
				resp.headers.set('Vary', 'Origin');
			}
			return resp;
		}

		// --- L2: R2 variant cache (global, permanent, ~20-50ms) ---
		// Only for transform requests where we know the output format
		const knownMime = mimeFromFormat(format);
		if (width > 0 && knownMime) {
			const variantKey = buildVariantKey(r2Key, width, quality, format);
			const variant = await env.FILES_BUCKET.get(variantKey);

			if (variant) {
				const headers: Record<string, string> = {
					'Cache-Control': cacheControl,
					'Content-Type': knownMime,
					'ETag': variant.httpEtag,
				};
				if (variant.size) {
					headers['Content-Length'] = variant.size.toString();
				}

				const response = new Response(variant.body, { headers });

				// Populate L1 cache for faster hits in this colo next time
				const toCache = response.clone();
				ctx.waitUntil(cache.put(cacheKey, toCache));

				if (origin) {
					response.headers.set('Access-Control-Allow-Origin', origin);
					response.headers.set('Vary', 'Origin');
				}
				return response;
			}
		}

		// --- L3: Fetch original from R2 + transform if needed ---
		const object = await env.FILES_BUCKET.get(r2Key);
		if (!object) {
			return new Response('File not found', { status: 404 });
		}

		const contentType = object.httpMetadata?.contentType || inferContentType(r2Key);

		// For resizable images with a width specified, use the Images binding
		if (isResizableImage(contentType) && width > 0) {
			const outputMime = formatToMime(format, contentType);
			const transformedEtag = buildTransformedEtag(object.httpEtag, width, quality, format);

			// Check If-None-Match BEFORE the expensive transform
			if (etagMatches(request.headers.get('If-None-Match'), transformedEtag)) {
				const headers: Record<string, string> = {
					'Cache-Control': cacheControl,
					'Content-Type': outputMime,
					'ETag': transformedEtag,
					...(origin && { 'Access-Control-Allow-Origin': origin }),
					...(origin && { 'Vary': 'Origin' }),
				};
				return new Response(null, { status: 304, headers });
			}

			try {
				const transformed = await env.IMAGES
					.input(object.body)
					.transform({ width, fit: 'scale-down' })
					.output({ format: outputMime, quality });

				// Read transformed bytes so we can store in R2 + Cache API + serve
				const bytes = await transformed.response().arrayBuffer();

				const headers = new Headers();
				headers.set('Cache-Control', cacheControl);
				headers.set('Content-Type', outputMime);
				headers.set('ETag', transformedEtag);
				headers.set('Content-Length', bytes.byteLength.toString());

				const response = new Response(bytes, { status: 200, headers });

				// Store in R2 as permanent variant (fire-and-forget)
				const variantKey = buildVariantKey(r2Key, width, quality, format);
				ctx.waitUntil(
					env.FILES_BUCKET.put(variantKey, bytes, {
						httpMetadata: { contentType: outputMime },
					})
				);

				// Store in L1 Cache API (fire-and-forget)
				const toCache = response.clone();
				toCache.headers.delete('Access-Control-Allow-Origin');
				toCache.headers.delete('Vary');
				ctx.waitUntil(cache.put(cacheKey, toCache));

				if (origin) {
					response.headers.set('Access-Control-Allow-Origin', origin);
					response.headers.set('Vary', 'Origin');
				}

				return response;
			} catch {
				// Transform failed (e.g. quota exhausted) — serve original from R2
				const fallback = await env.FILES_BUCKET.get(r2Key);
				if (!fallback) {
					return new Response('File not found', { status: 404 });
				}
				const headers: Record<string, string> = {
					'Content-Type': contentType,
					'Cache-Control': `public, max-age=${browserMaxAge}, s-maxage=${maxAge}`,
					'ETag': fallback.httpEtag,
					...(origin && { 'Access-Control-Allow-Origin': origin }),
					...(origin && { 'Vary': 'Origin' }),
				};
				if (fallback.size) {
					headers['Content-Length'] = fallback.size.toString();
				}
				return new Response(fallback.body, { headers });
			}
		}

		// Non-resizable or full-size: stream directly from R2
		const responseHeaders: Record<string, string> = {
			'Content-Type': contentType,
			'Cache-Control': `public, max-age=${browserMaxAge}, s-maxage=${maxAge}`,
			'ETag': object.httpEtag,
		};

		if (object.size) {
			responseHeaders['Content-Length'] = object.size.toString();
		}

		if (object.httpEtag && etagMatches(request.headers.get('If-None-Match'), object.httpEtag)) {
			if (origin) {
				responseHeaders['Access-Control-Allow-Origin'] = origin;
				responseHeaders['Vary'] = 'Origin';
			}
			return new Response(null, { status: 304, headers: responseHeaders });
		}

		const response = new Response(object.body, { headers: responseHeaders });

		// Cache non-transformed responses too (saves R2 reads)
		const toCache = response.clone();
		ctx.waitUntil(cache.put(cacheKey, toCache));

		if (origin) {
			response.headers.set('Access-Control-Allow-Origin', origin);
			response.headers.set('Vary', 'Origin');
		}

		return response;
	},
} satisfies ExportedHandler<Env>;
