/** "2026-08-14" → "14 Aug 2026". Installers shouldn't read ISO. Anything that
 * doesn't parse comes back as it arrived — never worse than before. */
export function fmtDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(`${iso.slice(0, 10)}T00:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-AU", { day: "numeric", month: "short", year: "numeric" });
}
