import { Suspense } from "react";
import CommandCenter from "@/components/CommandCenter";

/**
 * The console reads `?command=` and `?tour=1` with `useSearchParams`, which
 * forces client-side rendering up to the nearest Suspense boundary. Keeping
 * that boundary here lets the rest of the route prerender.
 */
export default function Page() {
  return (
    <Suspense fallback={<main className="auth-loading">VERIFYING ACCESS</main>}>
      <CommandCenter />
    </Suspense>
  );
}
