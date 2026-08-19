"use client";

import { useActionState } from "react";
import { createFirstAdmin, signIn } from "./actions";

export default function LoginForm({ firstRun }: { firstRun: boolean }) {
  const [loginState, loginAction, loggingIn] = useActionState(signIn, null);
  const [bootState, bootAction, booting] = useActionState(createFirstAdmin, null);

  if (firstRun) {
    return (
      <form action={bootAction}>
        <h1 className="auth-h">Create the first admin</h1>
        <p className="auth-p">
          No one has signed in yet. This creates the admin account that manages
          everyone else&rsquo;s access. It needs the <b>SETUP_KEY</b> from your
          Vercel environment variables — the same one the Setup page uses.
        </p>
        <label className="lbl" htmlFor="name">Your name</label>
        <input className="field" id="name" name="name" autoComplete="name" required />
        <label className="lbl" htmlFor="email">Email</label>
        <input className="field" id="email" name="email" type="email" autoComplete="email" required />
        <label className="lbl" htmlFor="password">Password <span className="hint">at least 10 characters</span></label>
        <input className="field" id="password" name="password" type="password" autoComplete="new-password" minLength={10} required />
        <label className="lbl" htmlFor="setup_key">SETUP_KEY</label>
        <input className="field" id="setup_key" name="setup_key" type="password" autoComplete="off" required />
        {bootState?.error && <div className="auth-err">{bootState.error}</div>}
        <button className="btn b-main" disabled={booting} type="submit">
          {booting ? "Creating…" : "Create admin & sign in"}
        </button>
      </form>
    );
  }

  return (
    <form action={loginAction}>
      <h1 className="auth-h">Sign in</h1>
      <label className="lbl" htmlFor="email">Email</label>
      <input className="field" id="email" name="email" type="email" autoComplete="email" required />
      <label className="lbl" htmlFor="password">Password</label>
      <input className="field" id="password" name="password" type="password" autoComplete="current-password" required />
      {loginState?.error && <div className="auth-err">{loginState.error}</div>}
      <button className="btn b-main" disabled={loggingIn} type="submit">
        {loggingIn ? "Signing in…" : "Sign in"}
      </button>
      <p className="auth-p" style={{ marginTop: 4 }}>
        Locked out? Any admin can reset your password on the Users page.
      </p>
    </form>
  );
}
