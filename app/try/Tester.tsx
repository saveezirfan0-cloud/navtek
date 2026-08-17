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
      const data = await response.json();
      setOut({ text: JSON.stringify(data, null, 2), ok: response.ok });
    } catch (error) {
      setOut({
        text: error instanceof Error ? error.message : "Could not read the file",
        ok: false,
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
