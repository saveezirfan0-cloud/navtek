"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/**
 * Re-fetches the page's server data on an interval, so "did my drop land"
 * answers itself instead of someone mashing reload after every eOrder.
 * Skips ticks while the tab is in the background — no point refreshing a
 * dashboard nobody is looking at.
 */
export default function AutoRefresh({ seconds = 30 }: { seconds?: number }) {
  const router = useRouter();
  useEffect(() => {
    const id = setInterval(() => {
      if (!document.hidden) router.refresh();
    }, seconds * 1000);
    return () => clearInterval(id);
  }, [router, seconds]);
  return null;
}
