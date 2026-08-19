/**
 * The staleness marker. The portal reads monday live; only when that fails
 * does it fall back to the cached list — and a stale cache must say so, out
 * loud, because a job list from three hours ago can send someone to a site
 * that was reallocated this morning. Rendered only when the backend flags the
 * data as more than an hour old.
 */
export default function Staleness({
  refreshedAt,
  stale,
}: {
  refreshedAt?: string | null;
  stale?: boolean;
}) {
  if (!stale) return null;

  let when = "a while ago";
  if (refreshedAt) {
    const ms = Date.now() - new Date(refreshedAt).getTime();
    if (Number.isFinite(ms) && ms >= 0) {
      const hours = Math.floor(ms / 3_600_000);
      when =
        hours < 1
          ? `${Math.max(1, Math.floor(ms / 60_000))}m ago`
          : hours < 48
            ? `${hours}h ago`
            : `${Math.floor(hours / 24)}d ago`;
    }
  }

  return (
    <div
      role="status"
      style={{
        margin: "10px 0",
        padding: "8px 12px",
        borderRadius: 8,
        background: "rgba(240, 173, 78, 0.15)",
        border: "1px solid rgba(240, 173, 78, 0.5)",
        fontSize: 13,
      }}
    >
      ⚠ Updated {when} — pull to refresh
    </div>
  );
}
