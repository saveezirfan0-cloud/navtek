"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { paletteSearch, type PaletteHit } from "./search-actions";
import { applyTheme, type Theme } from "./theme";
import type { NavGroup } from "./Sidebar";

/**
 * ⌘K / Ctrl+K, anywhere in the staff app: jump to a module, switch the
 * theme, or search the whole order ledger. Opens from the keyboard or the
 * sidebar's search button (the "navtek:palette" event).
 *
 * The ledger search runs through a server action under the caller's own
 * session — the palette shows order results only to logins that could open
 * the Orders pages anyway.
 */

export const OPEN_PALETTE_EVENT = "navtek:palette";

type Item =
  | { kind: "nav"; label: string; sub: string; href: string }
  | { kind: "theme"; label: string; theme: Theme }
  | { kind: "order"; label: string; sub: string; href: string; status: PaletteHit["status"] };

const THEME_ITEMS: Item[] = (["light", "dark", "system"] as Theme[]).map((t) => ({
  kind: "theme",
  theme: t,
  label: `Theme: ${t[0].toUpperCase()}${t.slice(1)}`,
}));

const STATUS_LABEL = { read: "Read", check: "Check", failed: "Failed" } as const;

export default function CommandPalette({
  groups,
  searchOrders,
}: {
  groups: NavGroup[];
  searchOrders: boolean;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  // The last ledger answer, tagged with the query it answered — hits and
  // "still searching" are derived from the tag instead of synced by effects.
  const [answer, setAnswer] = useState<{ q: string; hits: PaletteHit[] } | null>(null);
  const [rawSelected, setRawSelected] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const requestId = useRef(0);

  const openPalette = useCallback(() => {
    setOpen(true);
    setQ("");
    setAnswer(null);
    setRawSelected(0);
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        openPalette();
      }
      if (e.key === "Escape") setOpen(false);
    };
    const onOpen = () => openPalette();
    window.addEventListener("keydown", onKey);
    window.addEventListener(OPEN_PALETTE_EVENT, onOpen);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener(OPEN_PALETTE_EVENT, onOpen);
    };
  }, [openPalette]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  // The ledger search, debounced; stale responses lose to newer keystrokes.
  // The effect only schedules — state changes happen in the async callback.
  const needle = q.trim();
  const wantsSearch = open && searchOrders && needle.length >= 2;
  useEffect(() => {
    if (!wantsSearch) return;
    const id = ++requestId.current;
    const timer = setTimeout(async () => {
      const results = await paletteSearch(needle).catch(() => []);
      if (id === requestId.current) setAnswer({ q: needle, hits: results });
    }, 250);
    return () => clearTimeout(timer);
  }, [needle, wantsSearch]);

  const hits = useMemo(
    () => (wantsSearch && answer?.q === needle ? answer.hits : []),
    [wantsSearch, answer, needle],
  );
  const searching = wantsSearch && answer?.q !== needle;

  const items = useMemo<Item[]>(() => {
    const lower = needle.toLowerCase();
    const nav: Item[] = groups.flatMap((g) =>
      g.links
        .filter((l) => !lower || l.label.toLowerCase().includes(lower))
        .map((l) => ({ kind: "nav" as const, label: l.label, sub: g.label, href: l.href })),
    );
    const themes = THEME_ITEMS.filter(
      (t) => !lower || t.label.toLowerCase().includes(lower) || "theme".includes(lower),
    );
    const orders: Item[] = hits.map((h) => ({
      kind: "order",
      label: h.label,
      sub: h.sub,
      status: h.status,
      href: h.item_id ? `/orders/${h.item_id}` : "/",
    }));
    return [...orders, ...nav, ...themes];
  }, [groups, needle, hits]);

  // Clamped at use, not synced by an effect — the list can shrink under the
  // cursor between renders.
  const selected = Math.min(rawSelected, Math.max(0, items.length - 1));

  const run = useCallback(
    (item: Item) => {
      setOpen(false);
      if (item.kind === "theme") applyTheme(item.theme);
      else router.push(item.href);
    },
    [router],
  );

  if (!open) return null;

  return (
    <div className="cmdk-overlay" onClick={() => setOpen(false)}>
      <div
        className="cmdk"
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        onClick={(e) => e.stopPropagation()}
      >
        <input
          ref={inputRef}
          className="cmdk-input"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={
            searchOrders ? "Search orders, or jump to a page…" : "Jump to a page…"
          }
          aria-label="Search"
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setRawSelected(Math.min(selected + 1, items.length - 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setRawSelected(Math.max(selected - 1, 0));
            } else if (e.key === "Enter" && items[selected]) {
              e.preventDefault();
              run(items[selected]);
            }
          }}
        />
        <div className="cmdk-list" role="listbox">
          {searching && <div className="cmdk-note">Searching the ledger…</div>}
          {!searching && q.trim().length >= 2 && searchOrders && hits.length === 0 && (
            <div className="cmdk-note">No orders match “{q.trim()}”.</div>
          )}
          {items.map((item, i) => (
            <button
              key={`${item.kind}:${item.label}:${"href" in item ? item.href : item.theme}`}
              type="button"
              role="option"
              aria-selected={i === selected}
              className={`cmdk-item ${i === selected ? "sel" : ""}`}
              onMouseEnter={() => setRawSelected(i)}
              onClick={() => run(item)}
            >
              <span className="cmdk-label">
                {item.label}
                {item.kind === "order" && (
                  <span className={`pill p-${item.status}`} style={{ marginLeft: 8 }}>
                    {STATUS_LABEL[item.status]}
                  </span>
                )}
              </span>
              {"sub" in item && item.sub && <span className="cmdk-sub">{item.sub}</span>}
            </button>
          ))}
          {items.length === 0 && !searching && (
            <div className="cmdk-note">Nothing matches. Try a page name or an order.</div>
          )}
        </div>
        <div className="cmdk-foot">
          <span><kbd>↑</kbd><kbd>↓</kbd> navigate</span>
          <span><kbd>↵</kbd> open</span>
          <span><kbd>esc</kbd> close</span>
        </div>
      </div>
    </div>
  );
}
