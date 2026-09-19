/**
 * Typed fetch client for the CutPilot API.
 * - Same-origin `/api` (proxied by Next.js rewrites) so httpOnly cookies work.
 * - Sends the CSRF header on every request.
 * - Transparently refreshes the access token once on 401.
 */

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "/api";

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

interface RequestOptions {
  method?: Method;
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined | null>;
  signal?: AbortSignal;
  raw?: boolean;
}

let refreshPromise: Promise<boolean> | null = null;

async function tryRefresh(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      credentials: "include",
      headers: { "x-requested-with": "cutpilot" },
    })
      .then((r) => r.ok)
      .catch(() => false)
      .finally(() => {
        setTimeout(() => (refreshPromise = null), 0);
      });
  }
  return refreshPromise;
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const url = path.startsWith("http") ? path : `${API_BASE}${path}`;
  if (!query) return url;
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== null) params.set(k, String(v));
  }
  const qs = params.toString();
  return qs ? `${url}${url.includes("?") ? "&" : "?"}${qs}` : url;
}

export async function api<T>(path: string, opts: RequestOptions = {}, retry = true): Promise<T> {
  const headers: Record<string, string> = { "x-requested-with": "cutpilot" };
  let body: BodyInit | undefined;
  if (opts.body instanceof FormData || opts.body instanceof Blob) {
    body = opts.body;
  } else if (opts.body !== undefined) {
    headers["content-type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  const res = await fetch(buildUrl(path, opts.query), {
    method: opts.method ?? "GET",
    credentials: "include",
    headers,
    body,
    signal: opts.signal,
  });
  if (res.status === 401 && retry && !path.startsWith("/auth/")) {
    if (await tryRefresh()) return api<T>(path, opts, false);
  }
  if (!res.ok) {
    let code = "http_error";
    let message = res.statusText;
    let details: Record<string, unknown> = {};
    try {
      const data = await res.json();
      code = data?.error?.code ?? code;
      message = data?.error?.message ?? message;
      details = data?.error?.details ?? {};
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, code, message, details);
  }
  if (opts.raw) return res as unknown as T;
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const apiGet = <T>(path: string, query?: RequestOptions["query"]) => api<T>(path, { query });
export const apiPost = <T>(path: string, body?: unknown, query?: RequestOptions["query"]) =>
  api<T>(path, { method: "POST", body, query });
export const apiPut = <T>(path: string, body?: unknown, query?: RequestOptions["query"]) =>
  api<T>(path, { method: "PUT", body, query });
export const apiPatch = <T>(path: string, body?: unknown) => api<T>(path, { method: "PATCH", body });
export const apiDelete = <T>(path: string) => api<T>(path, { method: "DELETE" });

export function mediaUrl(assetId: string, variant: "stream" | "download" = "stream"): string {
  return `${API_BASE}/assets/${assetId}/${variant}`;
}
