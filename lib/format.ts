/** Shared display formatting. Safe in server and client components alike —
 * nothing here may import server-only modules. */

/** "20 Aug, 08:57 am", with the year added only when it isn't this year.
 * Was copy-pasted into every page that shows a timestamp; one drift (a page
 * quietly showing UTC) is why it lives here now. */
/** A link straight to the monday board row, or null when the account slug
 * isn't configured — callers render plain text then, never a dead link. */
export function mondayItemUrl(
  slug: string | null | undefined,
  boardId: number | null | undefined,
  itemId: string | number | null | undefined,
): string | null {
  if (!slug || !boardId || !itemId) return null;
  return `https://${slug}.monday.com/boards/${boardId}/pulses/${itemId}`;
}

export function when(iso: string) {
  const d = new Date(iso);
  const thisYear = d.getFullYear() === new Date().getFullYear();
  return d.toLocaleString("en-AU", {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
    ...(thisYear ? {} : { year: "numeric" }),
  });
}
