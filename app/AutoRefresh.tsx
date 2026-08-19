"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

/** Re-fetches the server component's data on an interval and whenever the tab
 * regains focus, so the dashboard and the portals track monday without anyone
 * hammering ⌘R. router.refresh() re-runs the server render in place — no
 * scroll jump, no form state lost, and nothing happens while the tab is
 * hidden, which is most of the life of a portal tab on an installer's phone. */
export default function AutoRefresh({ seconds = 30 }: { seconds?: number }) {
  const router = useRouter();

  useEffect(() => {
    const tick = () => {
      if (document.visibilityState === "visible") router.refresh();
    };
    const id = setInterval(tick, seconds * 1000);
    window.addEventListener("focus", tick);
    document.addEventListener("visibilitychange", tick);
    return () => {
      clearInterval(id);
      window.removeEventListener("focus", tick);
      document.removeEventListener("visibilitychange", tick);
    };
  }, [router, seconds]);

  return null;
}
