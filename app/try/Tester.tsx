"use client";

import { useRef, useState } from "react";

/**
 * Posts the raw file bytes straight to the Python parser. No server action in
 * between — a 300KB spreadsheet round-tripping through an action payload is
 * slower and buys nothing, since /api/py/parse touches no credentials.
 */
export default function Tester() {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [out, setOut] = useState<{ text: string; ok: boolean } | null>(null);

  async function send(file: File) {
    setOut({ text: `Reading ${file.name}…`, ok: true });
    try {
      const response = await fetch("/api/py/parse", {
        method: "POST",
        body: await file.arrayBuffer(),
      });
      const body = await response.text();

      // An HTML body means the request never reached the Python function —
      // it was answered by Next's 404 page or by Vercel's error page. Saying
      // "not valid JSON" there is true but useless, so diagnose instead.
      if (body.trimStart().startsWith("<")) {
        const health = await fetch("/api/py/health")
          .then((r) => (r.ok ? "responding" : `returned HTTP ${r.status}`))
          .catch(() => "unreachable");
        setOut({
          ok: false,
          text:
            `The parser returned a web page instead of data (HTTP ${response.status}).\n\n` +
            `The Python function is ${health}.\n\n` +
            (health === "responding"
              ? "So routing works but this request failed. Check the Logs tab in " +
                "Vercel for this deployment — the traceback will be there."
              : "So the Python function itself isn't running. Usual causes: " +
                "requirements.txt missing from the repository root, or api/_lib " +
                "not uploaded. Check both are in GitHub, then redeploy.") +
            `\n\n--- what came back ---\n${body.slice(0, 600)}`,
        });
        return;
      }

      setOut({ text: JSON.stringify(JSON.parse(body), null, 2), ok: response.ok });
    } catch (error) {
      setOut({
        ok: false,
        text: error instanceof Error ? error.message : "Could not read the file",
      });
    }
  }

  return (
    <>
      <div
        className={over ? "drop over" : "drop"}
        onClick={() => input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          const file = e.dataTransfer.files[0];
          if (file) send(file);
        }}
      >
        Choose a file, or drag one here
      </div>
      <input
        ref={input}
        type="file"
        accept=".xlsx"
        hidden
        onChange={(e) => e.target.files?.[0] && send(e.target.files[0])}
      />
      {out && <pre className={out.ok ? "out ok" : "out err"}>{out.text}</pre>}
    </>
  );
}
