"use client";

import { useState, useTransition } from "react";
import { runSweepAction } from "./actions";

/**
 * The "Run sweep now" button. The daily cron makes this same pass at 7am
 * AEST; this exists so testing shadow mode is a click, not a curl command
 * with a secret in it. The action re-checks admin server side.
 */
export default function RunSweep({ shadow }: { shadow: boolean }) {
  const [pending, start] = useTransition();
  const [note, setNote] = useState<string | null>(null);

  return (
    <div style={{ marginTop: 12 }}>
      <button
        className="act"
        type="button"
        disabled={pending}
        onClick={() =>
          start(async () => {
            setNote(null);
            const outcome = await runSweepAction();
            if (!outcome.ok) {
              setNote(outcome.error);
              return;
            }
            const r = outcome.result;
            if (!r.swept) {
              setNote(r.reason ?? "The sweep refused to run.");
              return;
            }
            const found = r.breaches?.length ?? 0;
            setNote(
              `Swept ${r.jobs_checked ?? 0} job${r.jobs_checked === 1 ? "" : "s"} — ` +
                (found === 0
                  ? "no SLA breaches."
                  : `${found} breach${found === 1 ? "" : "es"}${
                      r.shadow
                        ? " recorded (shadow — nothing sent). Details in the ledger below."
                        : " — escalated and texted. Details in the ledger below."
                    }`),
            );
          })
        }
      >
        {pending ? "Sweeping…" : "Run sweep now"}
      </button>
      <span className="tiny" style={{ marginLeft: 10 }}>
        {note ??
          (shadow
            ? "Same pass as the daily 7am run — records and logs, sends nothing."
            : "Same pass as the daily 7am run — live: escalates and texts.")}
      </span>
    </div>
  );
}
