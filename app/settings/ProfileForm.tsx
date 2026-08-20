"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import Toast from "../Toast";
import {
  changePasswordAction,
  signOutEverywhereAction,
  updateProfileAction,
} from "./actions";

/** Your own account: display name, password, and the "I left myself signed
 * in on the warehouse PC" button. Access flags stay on the admin's Users
 * page — this is only what any login may do to itself. */
export default function ProfileForm({
  name,
  email,
  readOnly,
}: {
  name: string;
  email: string;
  readOnly: boolean;
}) {
  const router = useRouter();
  const [draftName, setDraftName] = useState(name);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirmAll, setConfirmAll] = useState(false);
  const [toast, setToast] = useState<{ message: string; error?: boolean } | null>(null);
  const [savingName, startName] = useTransition();
  const [savingPass, startPass] = useTransition();
  const [signingOut, startSignOut] = useTransition();

  const saveName = () =>
    startName(async () => {
      const result = await updateProfileAction(draftName.trim());
      if (result.ok) {
        setToast({ message: "Name updated." });
        router.refresh(); // the sidebar's profile card re-renders server side
      } else {
        setToast({ message: `Not saved — ${result.error}`, error: true });
      }
    });

  const savePassword = () =>
    startPass(async () => {
      const result = await changePasswordAction({
        current_password: current,
        new_password: next,
      });
      if (result.ok) {
        setCurrent("");
        setNext("");
        setToast({
          message: "Password changed. Every other device has been signed out.",
        });
      } else {
        setToast({ message: `Not changed — ${result.error}`, error: true });
      }
    });

  return (
    <>
      <div className="form-grid">
        <label className="lbl">
          Name
          <input
            className="field"
            value={draftName}
            onChange={(e) => setDraftName(e.target.value)}
            disabled={readOnly}
            autoComplete="name"
          />
        </label>
        <label className="lbl">
          Email <span className="hint">— sign-in identity; an admin can change it</span>
          <input className="field" value={email} disabled />
        </label>
      </div>
      <button
        className="act"
        type="button"
        onClick={saveName}
        disabled={savingName || readOnly || !draftName.trim() || draftName.trim() === name}
      >
        {savingName ? "Saving…" : "Save name"}
      </button>

      <h3 style={{ fontSize: 15.5, margin: "22px 0 8px" }}>Change password</h3>
      <div className="form-grid">
        <label className="lbl">
          Current password
          <input
            className="field"
            type="password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            disabled={readOnly}
            autoComplete="current-password"
          />
        </label>
        <label className="lbl">
          New password <span className="hint">— at least 10 characters</span>
          <input
            className="field"
            type="password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            disabled={readOnly}
            autoComplete="new-password"
          />
        </label>
      </div>
      <button
        className="act"
        type="button"
        onClick={savePassword}
        disabled={savingPass || readOnly || !current || !next}
      >
        {savingPass ? "Changing…" : "Change password"}
      </button>
      <p className="tiny" style={{ marginTop: 8 }}>
        Changing it signs out every other device; this one stays signed in.
      </p>

      <h3 style={{ fontSize: 15.5, margin: "22px 0 8px" }}>Sessions</h3>
      {!confirmAll ? (
        <button
          className="act ghost"
          type="button"
          onClick={() => setConfirmAll(true)}
          disabled={readOnly}
        >
          Sign out everywhere…
        </button>
      ) : (
        <div className="ask" style={{ maxWidth: 420 }}>
          <label>End every session, including this one?</label>
          <div className="ask-row">
            <button
              className="btn b-warn"
              type="button"
              disabled={signingOut}
              onClick={() => startSignOut(() => signOutEverywhereAction())}
            >
              {signingOut ? "Signing out…" : "Yes, sign out everywhere"}
            </button>
            <button
              className="btn b-plain"
              type="button"
              onClick={() => setConfirmAll(false)}
            >
              Keep me signed in
            </button>
          </div>
        </div>
      )}

      {toast && (
        <Toast message={toast.message} error={toast.error} onDone={() => setToast(null)} />
      )}
    </>
  );
}
