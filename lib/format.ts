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

/** The timezone the business runs on. Every timestamp this app stores is UTC;
 * rendering without a zone gives each viewer their OWN browser's time, so the
 * same delivery read 11:58 pm in London and 8:58 am in Sydney and neither
 * matched what monday showed. Navtek work Australian eastern time, so that is
 * what the dashboard says — for everyone, wherever they are reading it. */
export const TZ = "Australia/Sydney";

/** The year it currently is in Sydney — not in the viewer's timezone, or the
 * year label appears and disappears depending on who is looking. */
function sydneyYear(d: Date): string {
  return d.toLocaleDateString("en-AU", { year: "numeric", timeZone: TZ });
}

export function when(iso: string) {
  const d = new Date(iso);
  const thisYear = sydneyYear(d) === sydneyYear(new Date());
  return d.toLocaleString("en-AU", {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
    timeZone: TZ,
    ...(thisYear ? {} : { year: "numeric" }),
  });
}
