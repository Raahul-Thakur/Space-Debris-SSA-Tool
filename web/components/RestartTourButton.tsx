"use client";

import { useRouter } from "next/navigation";
import { resetTour } from "@/components/ProductTour";

/**
 * Clears the "tour completed" flag and sends the visitor back to the console,
 * where the tour opens immediately via the `?tour=1` query parameter.
 */
export default function RestartTourButton({ inline = false }: { inline?: boolean }) {
  const router = useRouter();

  function restart() {
    resetTour();
    router.push("/?tour=1");
  }

  return (
    <button
      type="button"
      className={inline ? "docs-tour-inline" : "docs-tour"}
      onClick={restart}
    >
      {inline ? "start it again" : "RESTART TOUR"}
    </button>
  );
}
