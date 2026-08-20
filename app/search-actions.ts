"use server";

import { getRecent } from "@/lib/api";
import { currentUser } from "@/lib/auth";

/**
 * The command palette's order search. Runs server side with the shared
 * secret, gated on the caller's own session — the palette is available to
 * every staff login, but the ledger only answers to Orders access.
 */

export type PaletteHit = {
  item_id: number | null;
  label: string;
  sub: string;
  status: "read" | "check" | "failed";
};

export async function paletteSearch(q: string): Promise<PaletteHit[]> {
  const query = (q ?? "").trim();
  if (query.length < 2) return [];
  const user = await currentUser();
  if (!user || (!user.can_orders && !user.is_admin)) return [];

  const page = await getRecent({ q: query, limit: 8 });
  return page.ingests.map((r) => ({
    item_id: r.monday_item_id,
    label: r.item_name ?? r.file_name ?? `item ${r.monday_item_id ?? "?"}`,
    sub: [r.opportunity_id, r.file_name].filter(Boolean).join(" · "),
    status: r.status,
  }));
}
