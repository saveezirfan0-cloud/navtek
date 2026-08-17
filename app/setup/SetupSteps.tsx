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
    body,
    warn,
  }: {
    n: number;
    title: string;
    children: React.ReactNode;
    step: StepKey;
    label: string;
    body?: Record<string, unknown>;
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
        className={n === 2 ? "act ghost" : "act"}
        disabled={results[step] === "running"}
        onClick={() => go(step, body)}
      >
        {label}
      </button>
      <Output result={results[step] ?? null} />
    </div>
  );

  return (
    <>
      <Step n={1} step="plan" title="Preview the board changes" label="Preview">
        Lists the columns that would be added to TN Orders. Nothing is created.
        Read this before step 2. Anything already there shows as{" "}
        <code>exists</code>.
      </Step>

      <Step
        n={2}
        step="columns"
        title="Create the columns"
        label="Create columns"
        warn="This changes the live TN Orders board. Existing columns are left alone; only missing ones are added."
      >
        Adds the fifteen columns the automation writes to, and shows the ID of
        each.
      </Step>

      <Step n={3} step="installers" title="Set up the Installer Accounts board" label="Set up board">
        Uses your existing Installer Accounts board if there is one — set{" "}
        <code>INSTALLERS_BOARD_ID</code> in Vercel to name it explicitly —
        otherwise creates one. Either way it adds only the columns that are
        missing and issues a portal token to any account without one. Accounts
        are seeded only onto a genuinely empty board. Then it adds the{" "}
        <b>Installer</b> connect column to TN Orders and links the two boards.
      </Step>

      <div className="panel">
        <h2 className="step">
          <span className="step-n">4</span>Copy the environment variables
        </h2>
        <p>
          Paste these into Vercel under <b>Settings → Environment Variables</b>,
          then <b>Deployments → ⋯ → Redeploy</b>. The app reads them once at
          start-up, so nothing below works until it restarts.
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

      <Step n={5} step="sync" title="Copy the installers into the database" label="Sync installers">
        The portal looks a magic link up in the database, so an account added in
        monday stays invisible until this runs. Run it again whenever you add,
        deactivate or reissue an account.
      </Step>

      <div className="panel">
        <h2 className="step">
          <span className="step-n">6</span>Switch the automation on
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
          <span className="step-n">7</span>Test it
        </h2>
        <p>
          Open the <a href="/try">file tester</a> and drop an eOrder in to see
          what the parser reads. It writes nothing — not to monday, not to the
          database.
        </p>
      </div>
    </>
  );
}
