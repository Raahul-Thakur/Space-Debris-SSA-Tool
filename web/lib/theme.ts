/**
 * Light or dark, remembered on this device.
 *
 * Exposed as an external store for the same reason as the seen-events set:
 * `useSyncExternalStore` gives a defined server snapshot, so the toggle
 * renders without a hydration mismatch, and every reader is notified when the
 * value changes — including another tab, and including the operating system
 * changing its own appearance while the page is open.
 *
 * Deliberately not stored against the account. A preference about how a
 * screen looks belongs to the screen, not to the person: the same user on a
 * laptop at night and a phone in daylight wants different answers, and a
 * visitor who has never signed in wants one too. localStorage gives all of
 * that with no round trip and no schema. The cost is the one the user already
 * expects — clearing site data forgets it.
 *
 * Three states are representable but only two are stored. An absent value
 * means "follow the system", which is the default until somebody chooses;
 * once they do, their choice outranks the system in both directions, because
 * a person who picks light on a dark-themed machine means it.
 */

const KEY = "astra.theme";

export type Theme = "light" | "dark";

type Listener = () => void;
const listeners = new Set<Listener>();

let snapshot: Theme | null = null;

/**
 * The choice made in this page view, held independently of storage.
 *
 * Without it a refused write loses the choice immediately: the attribute
 * would be set on the document while the next read fell back through an
 * empty store to the system preference, leaving the page dark and the
 * toggle insisting it was light.
 */
let chosen: Theme | null = null;

function stored(): Theme | null {
  try {
    const value = window.localStorage.getItem(KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    // Private browsing, or site data blocked. Fall through to the system.
    return null;
  }
}

function systemTheme(): Theme {
  try {
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  } catch {
    return "light";
  }
}

function resolve(): Theme {
  return chosen ?? stored() ?? systemTheme();
}

function notify(): void {
  snapshot = null;
  for (const listener of listeners) listener();
}

/**
 * Apply the theme to the document.
 *
 * The attribute is only set when there is an explicit choice. Leaving it off
 * lets the `prefers-color-scheme` rules in the stylesheet apply unopposed,
 * which means the page keeps following the system if the system changes
 * later, without this module having to watch for it.
 */
function apply(theme: Theme | null): void {
  const root = document.documentElement;
  if (theme === null) delete root.dataset.theme;
  else root.dataset.theme = theme;
}

export function subscribeToTheme(listener: Listener): () => void {
  listeners.add(listener);

  const onStorage = (event: StorageEvent) => {
    if (event.key === null || event.key === KEY) {
      // Another tab is authoritative: it wrote what the device now wants.
      chosen = stored();
      apply(chosen);
      notify();
    }
  };
  window.addEventListener("storage", onStorage);

  // Only relevant while no explicit choice has been made, but harmless
  // otherwise: `resolve` ignores the system once something is stored.
  //
  // Guarded because `matchMedia` is not universally present -- jsdom has no
  // implementation, and neither do some embedded browsers. `systemTheme`
  // already tolerated its absence; this did not, so merely rendering the
  // toggle brought the whole page down wherever it was missing. Older Safari
  // exposes the object with `addListener` and no `addEventListener`, which
  // the second check covers by simply not subscribing.
  let query: MediaQueryList | null = null;
  try {
    query = window.matchMedia("(prefers-color-scheme: dark)");
  } catch {
    query = null;
  }
  const onSystem = () => notify();
  const watchable = typeof query?.addEventListener === "function";
  if (watchable) query!.addEventListener("change", onSystem);

  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
    if (watchable) query!.removeEventListener("change", onSystem);
  };
}

export function getThemeSnapshot(): Theme {
  snapshot ??= resolve();
  return snapshot;
}

/**
 * The server cannot know the device's preference.
 *
 * It reports light, and the client corrects it immediately after hydration.
 * Nothing flashes, because the inline script in the document head has
 * already set the attribute before the first paint; this value only decides
 * which label the toggle renders into the HTML, and that is replaced before
 * anyone reads it.
 */
export function getThemeServerSnapshot(): Theme {
  return "light";
}

export function setTheme(theme: Theme): void {
  chosen = theme;
  try {
    window.localStorage.setItem(KEY, theme);
  } catch {
    // The choice holds for this page view and is forgotten on reload, which
    // is better than refusing to switch at all.
  }
  apply(theme);
  notify();
}

/**
 * The script that runs before the first paint.
 *
 * Inlined into the document head, ahead of the stylesheet, so the attribute
 * is already correct when the page is first painted. Without it a visitor who
 * chose dark sees a white flash on every navigation while React hydrates.
 *
 * Kept deliberately tiny and wrapped in try/catch: it runs render-blocking on
 * every page, and a throw here would leave the document unstyled.
 */
export const THEME_BOOTSTRAP = `try{var t=localStorage.getItem("${KEY}");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}catch(e){}`;
