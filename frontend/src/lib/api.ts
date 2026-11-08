/**
 * Typed fetch wrapper for the SMSFlow API.
 * - Access token lives in memory only; the refresh token is an HttpOnly cookie.
 * - On 401 the client refreshes once (single-flight) and retries.
 */

export const API_BASE = "/api/v1";

let accessToken: string | null = null;
let refreshInFlight: Promise<boolean> | null = null;
let onSessionExpired: (() => void) | null = null;

export function setAccessToken(token: string | null) {
  accessToken = token;
}

export function getAccessToken() {
  return accessToken;
}

export function setSessionExpiredHandler(fn: () => void) {
  onSessionExpired = fn;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: unknown,
  ) {
    super(message);
  }
}

export async function refreshSession(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      try {
        const res = await fetch(`${API_BASE}/auth/refresh`, {
          method: "POST",
          credentials: "include",
          headers: { "X-Requested-With": "SMSFlow" },
        });
        if (!res.ok) {
          setAccessToken(null);
          return false;
        }
        const data = (await res.json()) as { access_token: string };
        setAccessToken(data.access_token);
        return true;
      } catch {
        return false;
      } finally {
        setTimeout(() => (refreshInFlight = null), 0);
      }
    })();
  }
  return refreshInFlight;
}

type Query = Record<string, string | number | boolean | undefined | null>;

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  query?: Query;
  form?: FormData;
  headers?: Record<string, string>;
  raw?: boolean;
}

function buildUrl(path: string, query?: Query) {
  const url = `${API_BASE}${path}`;
  if (!query) return url;
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== null && v !== "") params.set(k, String(v));
  }
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

async function doFetch(path: string, opts: RequestOptions): Promise<Response> {
  const headers: Record<string, string> = { "X-Requested-With": "SMSFlow", ...(opts.headers ?? {}) };
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  return fetch(buildUrl(path, opts.query), { method: opts.method ?? "GET", headers, body, credentials: "include" });
}

export async function apiRaw(path: string, opts: RequestOptions = {}): Promise<Response> {
  let res = await doFetch(path, opts);
  if (res.status === 401 && !path.startsWith("/auth/login") && !path.startsWith("/auth/refresh")) {
    if (await refreshSession()) res = await doFetch(path, opts);
    else onSessionExpired?.();
  }
  if (!res.ok) {
    let code = "http_error";
    let message = res.statusText || "Request failed";
    let details: unknown;
    try {
      const data = await res.json();
      if (data?.error) {
        code = data.error.code;
        message = data.error.message;
        details = data.error.details;
      } else if (Array.isArray(data?.detail)) {
        code = "validation_failed";
        message = data.detail
          .map((d: { loc?: (string | number)[]; msg: string }) => `${(d.loc ?? []).slice(1).join(".")}: ${d.msg}`)
          .join("; ");
      } else if (typeof data?.detail === "string") message = data.detail;
    } catch {
      /* non-JSON */
    }
    throw new ApiError(res.status, code, message, details);
  }
  return res;
}

export async function api<T = unknown>(path: string, opts: RequestOptions = {}): Promise<T> {
  const res = await apiRaw(path, opts);
  if (res.status === 204) return undefined as T;
  const type = res.headers.get("content-type") ?? "";
  return (type.includes("application/json") ? res.json() : res.text()) as Promise<T>;
}

export async function download(path: string, filename: string, query?: Query) {
  const res = await apiRaw(path, { query });
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export async function openHtml(path: string) {
  const res = await apiRaw(path);
  const html = await res.text();
  const w = window.open("", "_blank");
  if (w) {
    w.document.open();
    w.document.write(html);
    w.document.close();
  }
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return "Something went wrong";
}
