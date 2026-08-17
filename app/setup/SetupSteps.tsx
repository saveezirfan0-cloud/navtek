"use client";

import { useState } from "react";
import { runStep, type Result } from "./actions";

type StepKey = "plan" | "columns" | "installers" | "env" | "sync" | "webhook";

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
      {copyable && (
        <button
          className="act ghost"
          style={{ marginTop: 12 }}
          onClick={() => navigator.clipboard.writeText(copyable)}
        >
          Copy
        </button>
      )}
      <pre className="out ok">
        {log ? log.join("\n") + "\n\n" : ""}
        {JSON.stringify(rest, null, 2)}
      </pre>
    </>
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

  const Step = ({
    n,
    title,
    children,
    step,
    label,
    ghost,
    warn,
  }: {
    n: string;
    title: string;
    children: React.ReactNode;
    step: StepKey;
    label: string;
    ghost?: boolean;
    warn?: string;
  }) => (
    <div className="panel">
      <h2 className="step">
        <span className="step-n">{n}</span>
        {title}
      </h2>
      <p>{children}</p>
      {warn && <div className="warnbox">{warn}</div>}
      <button
        className={ghost ? "act ghost" : "act"}
        disabled={results[step] === "running"}
        onClick={() => go(step)}
      >
        {label}
      </button>
      <Output result={results[step] ?? null} />
    </div>
  );

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

      <Step n="1" step="plan" title="Preview the board changes" label="Preview" ghost>
        Lists the columns that would be added to TN Orders. Nothing is created.
        Anything already there shows as <code>exists</code>.
      </Step>

      <Step
        n="2"
        step="columns"
        title="Create the columns"
        label="Create columns"
        warn="This changes the live TN Orders board. Existing columns are left alone; only missing ones are added."
      >
        Adds the columns the automation writes to, and shows the ID of each.
      </Step>

      <div className="panel">
        <h2 className="step">
          <span className="step-n">3</span>Copy the environment variables
        </h2>
        <p>
          Paste these into Vercel under <b>Settings → Environment Variables</b>,
          then <b>Deployments → ⋯ → Redeploy</b>. The app reads them once at
          start-up, so step 4 won&rsquo;t work until it restarts.
        </p>
        <button
          className="act ghost"
          disabled={results.env === "running"}
          onClick={() => go("env")}
        >
          Show variables
        </button>
        <Output result={results.env ?? null} />
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
        <Output result={results.webhook ?? null} />
      </div>

      <div className="panel">
        <h2 className="step">
          <span className="step-n">5</span>Test it
        </h2>
        <p>
          Drop an eOrder into the <a href="/try">file tester</a> to check the
          parser reads it — that writes nothing anywhere. Then drop the same
          file onto the eOrder column of a row in TN Orders and watch the row
          fill in.
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
        step="installers"
        title="Set up the Installer Accounts board"
        label="Set up board"
        ghost
      >
        Uses your existing board if <code>INSTALLERS_BOARD_ID</code> is set in
        Vercel — otherwise creates one. Either way it adds only the columns that
        are missing and issues a portal token to any account without one.
        Accounts are seeded only onto a genuinely empty board.
      </Step>

      <Step
        n="B"
        step="sync"
        title="Copy the installers into the database"
        label="Sync installers"
        ghost
      >
        The portal looks a magic link up in the database, so an account added in
        monday stays invisible until this runs. Run it again whenever you add,
        deactivate or reissue an account.
      </Step>
    </>
  );
}
