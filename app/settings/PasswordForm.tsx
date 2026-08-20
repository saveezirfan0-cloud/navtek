"use client";

import { useState, useTransition } from "react";
import Toast from "../Toast";
import { changePasswordAction } from "./actions";

/** Change your own sign-in password. The current password is required — a
 * walked-away-from laptop must not be enough to take the account over — and
 * a successful change signs out every other device. */
export default function PasswordForm() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [toast, setToast] = useState<{ message: string; error?: boolean } | null>(null);
  const [saving, startSaving] = useTransition();

  const save = () => {
    if (!current || !next) {
      setToast({ message: "Enter your current password and a new one.", error: true });
      return;
    }
    if (next !== confirm) {
      setToast({ message: "The new passwords don't match.", error: true });
      return;
    }
    startSaving(async () => {
      const result = await changePasswordAction({
        current_password: current,
        new_password: next,
      });
      if (result.ok) {
        setCurrent("");
        setNext("");
        setConfirm("");
        setToast({ message: "Password changed. Other devices have been signed out." });
      } else {
        setToast({ message: `Not changed — ${result.error}`, error: true });
      }
    });
  };

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        save();
      }}
      style={{ maxWidth: 420 }}
    >
      <label className="lbl" htmlFor="pw-current">
        Current password
        <input
          id="pw-current"
          className="field"
          type="password"
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
          autoComplete="current-password"
          required
        />
      </label>
      <label className="lbl" htmlFor="pw-new">
        New password <span className="hint">— at least 10 characters</span>
        <input
          id="pw-new"
          className="field"
          type="password"
          value={next}
          onChange={(e) => setNext(e.target.value)}
          autoComplete="new-password"
          minLength={10}
          required
        />
      </label>
      <label className="lbl" htmlFor="pw-confirm">
        New password, again
        <input
          id="pw-confirm"
          className="field"
          type="password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          autoComplete="new-password"
          minLength={10}
          required
        />
      </label>
      <div style={{ marginTop: 10 }}>
        <button className="act" type="submit" disabled={saving}>
          {saving ? "Changing…" : "Change password"}
        </button>
      </div>
      <p className="tiny" style={{ marginTop: 10 }}>
        Changing it signs you out everywhere else — only this browser stays
        signed in.
      </p>

      {toast && (
        <Toast
          message={toast.message}
          error={toast.error}
          onDone={() => setToast(null)}
        />
      )}
    </form>
  );
}
