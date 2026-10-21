/** Classify resource events for the browser's no-external-requests assertion. */
export function isLocalResource(resource: string, origin: string): boolean {
  try {
    const url = new URL(resource);
    const app = new URL(origin);
    if (url.protocol === "data:") return true;
    return (
      ["http:", "https:"].includes(app.protocol) &&
      ["http:", "https:", "blob:"].includes(url.protocol) &&
      url.origin === app.origin
    );
  } catch {
    return false;
  }
}
