/**
 * Where to send someone after they sign in, when it was not the console.
 *
 * Kept in session storage rather than a query string because the OAuth round
 * trip always comes back to `/`: Supabase only redirects to allow-listed URLs,
 * and widening that list per page would loosen a security setting to save a
 * click. The console reads this on arrival and forwards.
 */
const KEY = "astra.return-to";

/** Only same-site paths, so a stored value can never become an open redirect. */
function isLocalPath(path: string): boolean {
  return path.startsWith("/") && !path.startsWith("//") && !path.startsWith("/\\");
}

export function rememberReturnTo(path: string) {
  if (!isLocalPath(path)) return;
  try {
    window.sessionStorage.setItem(KEY, path);
  } catch {
    // Without storage the visitor lands on the console; not worth failing over.
  }
}

export function consumeReturnTo(): string | null {
  try {
    const path = window.sessionStorage.getItem(KEY);
    if (path) window.sessionStorage.removeItem(KEY);
    return path && isLocalPath(path) ? path : null;
  } catch {
    return null;
  }
}
