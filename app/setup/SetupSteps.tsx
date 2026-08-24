"use client";

import Link from "next/link";
import { useState } from "react";
import { runStep, type Result } from "./actions";

type StepKey = "plan" | "columns" | "installers" | "env" | "sync" | "webhook" | "selftest";

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      className="act ghost"
      style={{ marginTop: 12 }}
      onClick={() => {
        navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }}
    >
      {copied ? "Copied ✓" : "Copy"}
    </button>
  );
}

function Output({ result }: { result: Result | "running" | null }) {
  if (!result) return null;
  if (result === "running") return <pre className="out">Working…</pre>;
  if (!result.ok) return <pre className="out err">{result.error}</pre>;

  const data = result.data as Record<string, unknown>;
  const log = Array.isArray(data?.log) ? (data.log as string[]) : null;
  const rest = log
    ? Object.fromEntries(Object.entries(data).filter(([k]) => k !== "log"))
    : data;

  const copyable =
    typeof data?.env_raw === "string"
      ? (data.env_raw as string)
      : data?.column_ids
        ? JSON.stringify(data.column_ids)
        : null;

  return (
    <>
      {copyable && <CopyButton text={copyable} />}
      <pre className="out ok">
        {log ? log.join("\n") + "\n\n" : ""}
        {JSON.stringify(rest, null, 2)}
      </pre>
    </>
  );
}

/* Declared at module level, not inside SetupSteps — a component created
   during render is remounted (state and all) on every parent render, which
   is why the lint rule bans it. State comes in as props instead. */
function Step({
  n,
  title,
  children,
  label,
  ghost,
  warn,
  result,
  onRun,
}: {
  n: string;
  title: string;
  children: React.ReactNode;
  label: string;
  ghost?: boolean;
  warn?: string;
  result: Result | "running" | null;
  onRun: () => void;
}) {
  return (
    <div className="panel">
      <h2 className="step">
        <span className="step-n">{n}</span>
        {title}
      </h2>
      <p>{children}</p>
      {warn && <div className="warnbox">{warn}</div>}
      <button
        className={ghost ? "act ghost" : "act"}
        disabled={result === "running"}
        onClick={onRun}
      >
        {label}
      </button>
      <Output result={result} />
    </div>
  );
}

export default function SetupSteps() {
  const [results, setResults] = useState<Record<string, Result | "running" | null>>({});
  const [url, setUrl] = useState("");

  const go = async (step: StepKey, body?: Record<string, unknown>) => {
    setResults((r) => ({ ...r, [step]: "running" }));
    const result = await runStep(step, body);
    setResults((r) => ({ ...r, [step]: result }));
  };

  return (
    <>
      {/* ---------------- The order automation ---------------- */}
      <div className="head" style={{ paddingTop: 8 }}>
        <h2 style={{ fontSize: 20, margin: 0 }}>The order automation</h2>
        <p>
          These five get eOrders reading into monday. Nothing here depends on
          the installer portal.
        </p>
      </div>

      <Step n="1" title="Preview the board changes" label="Preview" ghost
            result={results.plan ?? null} onRun={() => go("plan")}>
        Lists the columns that would be added to TN Orders. Nothing is created.
        Anything already there shows as <code>exists</code>.
      </Step>

      <Step
        n="2"
        title="Create the columns"
        label="Create columns"
        warn="This changes the live TN Orders board. Existing columns are left alone; only missing ones are added."
        result={results.columns ?? null}
        onRun={() => go("columns")}
      >
        Adds the columns the automation writes to, and shows the ID of each.
      </Step>

      <div className="panel">
        <h2 className="step">
          <span className="step-n">3</span>Check the columns were found
        </h2>
        <p>
          The app reads column IDs off the board by name, so there is nothing to
          paste and no redeploy needed. This confirms it can see all of them —{" "}
          <code>unmapped</code> should come back empty.
        </p>
        <button
          className="act ghost"
          disabled={results.env === "running"}
          onClick={() => go("env")}
        >
          Check columns
        </button>
        <Output result={results.env ?? null} />
        <p style={{ marginTop: 14, marginBottom: 0, fontSize: 14 }}>
          The <code>COLUMN_IDS</code> line in that output is optional — setting
          it in Vercel pins the IDs so a renamed column can&rsquo;t silently
          change what gets written. Everything works without it.
        </p>
      </div>

      <div className="panel">
        <h2 className="step">
          <span className="step-n">4</span>Switch the automation on
        </h2>
        <p>
          Registers the monday webhook against the <b>eOrder column only</b>, so
          dropping a DocuSign file on the existing files column still does
          nothing. Running it twice is safe — an existing webhook is reused
          rather than doubled. Paste this app&rsquo;s own address below.
        </p>
        <input
          className="field"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://your-app.vercel.app"
        />
        <button
          className="act"
          disabled={!url.startsWith("https://") || results.webhook === "running"}
          onClick={() => go("webhook", { url })}
        >
          Register webhook
        </button>
        <p>
          <b>Re-register</b> after changing <code>WEBHOOK_SECRET</code>. The
          secret is baked into the registered URL as <code>?hook=</code>, and
          monday can neither change a webhook&rsquo;s address nor report it
          back — so a rotated secret leaves every delivery being turned away
          while the ordinary button above still says &ldquo;already
          registered&rdquo;. Rejected deliveries show on{" "}
          <Link href="/deliveries">Deliveries</Link>.
        </p>
        <button
          className="act ghost"
          disabled={!url.startsWith("https://") || results.webhook === "running"}
          onClick={() => go("webhook", { url, force: true })}
        >
          Re-register (replace existing)
        </button>
        <Output result={results.webhook ?? null} />
      </div>

      <div className="panel">
        <h2 className="step">
          <span className="step-n">5</span>Check everything works
        </h2>
        <p>
          Checks the monday token, the board, the columns, the parser, the
          webhook and the database, and says which are working. Read-only —
          it changes nothing.
        </p>
        <button
          className="act"
          disabled={results.selftest === "running"}
          onClick={() => go("selftest")}
        >
          Run the check
        </button>
        <Output result={results.selftest ?? null} />
        <p style={{ marginTop: 14, marginBottom: 0, fontSize: 14 }}>
          All green? Drop an eOrder onto the eOrder column of a row in TN Orders
          and watch it fill in. To check a file without touching the board, use
          the <a href="/try">file tester</a>.
        </p>
      </div>

      {/* ---------------- The installer portal ---------------- */}
      <div className="head" style={{ paddingTop: 26 }}>
        <h2 style={{ fontSize: 20, margin: 0 }}>The installer portal — later</h2>
        <p>
          Not needed for the order automation. Leave these until the orders side
          is running properly. Until then the Installer column stays empty and
          no order is flagged because of it.
        </p>
      </div>

      <Step
        n="A"
        title="Set up the Installer Accounts board"
        label="Set up board"
        ghost
        result={results.installers ?? null}
        onRun={() => go("installers")}
      >
        Uses your existing board if <code>INSTALLERS_BOARD_ID</code> is set in
        Vercel — otherwise creates one. Either way it adds only the columns that
        are missing and issues a portal token to any account without one.
        Accounts are seeded only onto a genuinely empty board. It also switches
        on <b>auto-onboarding</b>: from then on, a row added or edited on the
        board issues its own token, syncs itself into the database, and emails
        the coordinator their portal link — no more pressing these steps per
        account.
      </Step>

      <Step
        n="B"
        title="Copy the installers into the database"
        label="Sync installers"
        ghost
        result={results.sync ?? null}
        onRun={() => go("sync")}
      >
        The portal looks a magic link up in the database, so an account added in
        monday stays invisible until this runs. With auto-onboarding registered
        (step A), board changes sync themselves — this button is the manual
        catch-up for anything added before that, and a safe way to force a
        re-sync any time.
      </Step>
    </>
  );
}
