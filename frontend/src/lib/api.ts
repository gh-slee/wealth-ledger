import type { components } from "./schema";
export type Models = components["schemas"];
export type Locale = "en-CA" | "zh-TW" | "zh-CN";
export type Currency = "CAD" | "USD" | "TWD";
export type Report = Models["ReportView"];
export type Job = Models["JobView"];
export type Portfolio = Models["PortfolioView"];
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
  ) {
    super(code);
  }
}
let csrf: string | null = null;
let generation = 0;
const controllers = new Set<AbortController>();
export function clearTransport() {
  generation++;
  csrf = null;
  for (const controller of controllers) controller.abort();
  controllers.clear();
}
async function transport<T>(
  path: string,
  consume: (response: Response) => Promise<T>,
  init: RequestInit = {},
  signal?: AbortSignal,
): Promise<T> {
  const controller = new AbortController();
  controllers.add(controller);
  const abort = () => controller.abort();
  signal?.addEventListener("abort", abort, { once: true });
  if (signal?.aborted) controller.abort();
  const started = generation;
  try {
    const response = await fetch("/api/v1" + path, {
      ...init,
      credentials: "same-origin",
      cache: "no-store",
      signal: controller.signal,
    });
    if (started !== generation)
      throw new DOMException("Request context changed", "AbortError");
    if (!response.ok) {
      const value = await response.json().catch(() => ({}));
      if (started !== generation)
        throw new DOMException("Request context changed", "AbortError");
      if (response.status === 401 && !path.endsWith("/auth/login")) {
        clearTransport();
        window.dispatchEvent(new Event("ledger:unauthorized"));
      }
      throw new ApiError(
        response.status,
        value.error?.code ?? "request_failed",
      );
    }
    const value = await consume(response);
    if (started !== generation)
      throw new DOMException("Request context changed", "AbortError");
    return value;
  } finally {
    controllers.delete(controller);
    signal?.removeEventListener("abort", abort);
  }
}
export async function read<T>(path: string, signal?: AbortSignal): Promise<T> {
  return transport(path, (response) => response.json(), {}, signal);
}
export async function readChart(
  path: string,
  signal?: AbortSignal,
): Promise<Blob> {
  return transport(
    path,
    (response) => {
      if (response.headers.get("content-type")?.split(";")[0] !== "image/png")
        throw new ApiError(409, "artifact_integrity");
      return response.blob();
    },
    {},
    signal,
  );
}
async function csrfToken() {
  if (!csrf) csrf = (await read<Models["CsrfView"]>("/auth/csrf")).csrf_token;
  return csrf;
}
export async function mutate<T>(
  path: string,
  body?: unknown,
  method = "POST",
  key?: string,
): Promise<T> {
  const started = generation;
  const headers: Record<string, string> = { "X-CSRF-Token": await csrfToken() };
  if (started !== generation)
    throw new DOMException("Request context changed", "AbortError");
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (key) headers["Idempotency-Key"] = key;
  const value = await transport(
    path,
    async (response) => (response.status === 204 ? undefined : response.json()),
    {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    },
  );
  if (value?.csrf_token) csrf = value.csrf_token;
  return value as T;
}
export async function upload(
  portfolio: string,
  file: File,
  kind: string,
): Promise<Models["UploadView"]> {
  const started = generation;
  const token = await csrfToken();
  if (started !== generation)
    throw new DOMException("Request context changed", "AbortError");
  return transport(
    `/portfolios/${portfolio}/uploads?kind=${kind}&filename=${encodeURIComponent(file.name)}`,
    (response) => response.json(),
    {
      method: "POST",
      headers: {
        "X-CSRF-Token": token,
        "Content-Type": "application/octet-stream",
      },
      body: file,
    },
  );
}
export async function download(
  portfolio: string,
  artifact: Models["Artifact"],
): Promise<void> {
  return downloadFile(
    `/portfolios/${portfolio}/artifacts/${artifact.id}`,
    artifact.filename,
  );
}
export async function downloadFile(
  path: string,
  filename: string,
): Promise<void> {
  const started = generation;
  const blob = await transport(path, (response) => response.blob());
  if (started !== generation) return;
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export const scope = (portfolio: string) => `/portfolios/${portfolio}`;
