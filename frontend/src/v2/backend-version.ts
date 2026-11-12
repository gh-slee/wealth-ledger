export async function detectBackendVersion(signal: AbortSignal) {
  const response = await fetch("/api/v2/auth/csrf", {
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    signal,
    headers: { Accept: "application/json" },
  });

  // The SQLite server leaves unknown API paths unhandled. Its existing
  // session check must run before requesting a token for an anonymous session.
  if (response.status === 404) return "v1";
  if (!response.ok) throw new Error("Could not detect the API version");

  const value = await response.json();
  if (
    typeof value?.authenticated !== "boolean" ||
    typeof value.csrf_token !== "string" ||
    !/^[a-f0-9]{64}$/.test(value.csrf_token)
  ) {
    throw new Error("Invalid V2 CSRF response");
  }
  return "v2";
}
