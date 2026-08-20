"use client";

import { useState, useTransition } from "react";
import type { NotificationSettings } from "@/lib/api";
import Toast from "../Toast";
import { saveNotificationsAction, sendTestEmailAction } from "./actions";

/** The email-alert configuration: who hears about ⚠️ Check and ❌ Failed
 * reads, and whether each status warrants a send at all. Saved explicitly —
 * a half-typed address list must not start receiving production alerts. */
export default function NotificationsForm({
  initial,
  readOnly,
}: {
  initial: NotificationSettings;
  readOnly: boolean;
}) {
  const [emails, setEmails] = useState(initial.emails.join("\n"));
  const [notifyCheck, setNotifyCheck] = useState(initial.notify_check);
  const [notifyFailed, setNotifyFailed] = useState(initial.notify_failed);
  const [toast, setToast] = useState<{ message: string; error?: boolean } | null>(null);
  const [saving, startSaving] = useTransition();
  const [testing, startTesting] = useTransition();

  const save = () =>
    startSaving(async () => {
      const result = await saveNotificationsAction({
        emails: emails
          .split(/[\n,;]/)
          .map((e) => e.trim())
          .filter(Boolean),
        notify_check: notifyCheck,
        notify_failed: notifyFailed,
      });
      setToast(
        result.ok
          ? { message: "Notification settings saved." }
          : { message: `Not saved — ${result.error}`, error: true },
      );
    });

  const test = () =>
    startTesting(async () => {
      const result = await sendTestEmailAction();
      setToast(
        result.ok
          ? { message: `Test sent to ${result.to.join(", ")}.` }
          : { message: `Test failed — ${result.error}`, error: true },
      );
    });

  return (
    <>
      <label className="lbl" htmlFor="notify-emails">
        Notification emails{" "}
        <span className="hint">— one address per line; they all get every alert</span>
        <textarea
          id="notify-emails"
          className="field"
          rows={4}
          value={emails}
          onChange={(e) => setEmails(e.target.value)}
          placeholder={"ops@example.com.au\ndispatch@example.com.au"}
          disabled={readOnly}
          style={{ marginTop: 5, resize: "vertical", fontFamily: "inherit" }}
        />
      </label>

      <div className="check-row">
        <label>
          <input
            type="checkbox"
            checked={notifyCheck}
            onChange={(e) => setNotifyCheck(e.target.checked)}
            disabled={readOnly}
          />
          Email when a read lands as <b>⚠️ Check</b>
        </label>
        <label>
          <input
            type="checkbox"
            checked={notifyFailed}
            onChange={(e) => setNotifyFailed(e.target.checked)}
            disabled={readOnly}
          />
          Email when a read <b>❌ Fails</b>
        </label>
      </div>

      <div>
        <button className="act" type="button" onClick={save} disabled={saving || readOnly}>
          {saving ? "Saving…" : "Save changes"}
        </button>
        <button
          className="act ghost"
          type="button"
          onClick={test}
          disabled={testing || readOnly}
          title="Sends a test email to the saved recipients"
        >
          {testing ? "Sending…" : "Send a test email"}
        </button>
      </div>
      <p className="tiny" style={{ marginTop: 10 }}>
        The test goes to the last <b>saved</b> list — save first if you just
        changed it. Each order emails at most once per file and status, so a
        webhook retry can&rsquo;t flood an inbox.
      </p>

      {toast && (
        <Toast
          message={toast.message}
          error={toast.error}
          onDone={() => setToast(null)}
        />
      )}
    </>
  );
}
