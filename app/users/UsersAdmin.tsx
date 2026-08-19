"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import type { AuthUser, InstallerAccountRef } from "@/lib/api";
import { createUserAction, startPreviewAction, updateUserAction } from "./actions";

export default function UsersAdmin({
  me,
  users,
  accounts,
}: {
  me: AuthUser;
  users: AuthUser[];
  accounts: InstallerAccountRef[];
}) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [error, setError] = useState<string | null>(null);

  const update = (input: Parameters<typeof updateUserAction>[0]) =>
    start(async () => {
      setError(null);
      const result = await updateUserAction(input);
      if (result.ok) router.refresh();
      else setError(result.error);
    });

  return (
    <>
      {error && (
        <div className="panel">
          <div className="warnbox"><b>That didn&rsquo;t save.</b> {error}</div>
        </div>
      )}

      <div className="panel">
        <h2>Everyone with a login</h2>
        <p>
          Changes apply on the person&rsquo;s next click — switching someone off
          signs them out everywhere, immediately.
        </p>
        {users.length === 0 ? (
          <p className="empty">No users yet.</p>
        ) : (
          <div className="scroll-x">
            <table>
              <thead>
                <tr>
                  <th>User</th>
                  <th>Orders</th>
                  <th>Installer</th>
                  <th>Installer account</th>
                  <th>Admin</th>
                  <th>Active</th>
                  <th>Password</th>
                  <th>See their view</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => {
                  const self = u.id === me.id;
                  return (
                    <tr key={u.id} style={{ opacity: u.active ? 1 : 0.5 }}>
                      <td>
                        <div style={{ fontWeight: 600 }}>
                          {u.name}
                          {self && <span className="pill p-read" style={{ marginLeft: 8 }}>you</span>}
                        </div>
                        <div className="mono" style={{ color: "var(--mid)" }}>{u.email}</div>
                      </td>
                      <td>
                        <Toggle
                          on={u.can_orders}
                          disabled={pending || u.is_admin}
                          label={`Orders access for ${u.name}`}
                          onFlip={(on) => update({ id: u.id, can_orders: on })}
                        />
                        {u.is_admin && <div className="tiny">always, as admin</div>}
                      </td>
                      <td>
                        <Toggle
                          on={u.can_installer}
                          disabled={pending}
                          label={`Installer access for ${u.name}`}
                          onFlip={(on) => update({ id: u.id, can_installer: on })}
                        />
                      </td>
                      <td>
                        <select
                          className="field"
                          style={{ marginBottom: 0, minWidth: 160 }}
                          aria-label={`Installer account for ${u.name}`}
                          value={u.installer_account_id ?? ""}
                          disabled={pending}
                          onChange={(e) =>
                            update({ id: u.id, installer_account_id: e.target.value || null })
                          }
                        >
                          <option value="">— none —</option>
                          {accounts.map((a) => (
                            <option key={a.id} value={a.id}>
                              {a.name}{a.active ? "" : " (inactive)"}
                            </option>
                          ))}
                        </select>
                        {u.can_installer && !u.installer_account_id && (
                          <div className="tiny warn">needed for the portal</div>
                        )}
                      </td>
                      <td>
                        <Toggle
                          on={u.is_admin}
                          disabled={pending || self}
                          label={`Admin for ${u.name}`}
                          onFlip={(on) => update({ id: u.id, is_admin: on })}
                        />
                        {self && <div className="tiny">not your own</div>}
                      </td>
                      <td>
                        <Toggle
                          on={u.active}
                          disabled={pending || self}
                          label={`Active for ${u.name}`}
                          onFlip={(on) => update({ id: u.id, active: on })}
                        />
                      </td>
                      <td>
                        <ResetPassword
                          disabled={pending}
                          onReset={(password) => update({ id: u.id, password })}
                        />
                      </td>
                      <td>
                        {/* What would this login see? Renders the app with
                            their access flags — read-only, clearly bannered,
                            no session minted for them. */}
                        <button
                          className="btn-ghost"
                          type="button"
                          disabled={pending || self}
                          title={self ? "You're already seeing your own view" : `Preview the app as ${u.name}`}
                          onClick={() =>
                            start(async () => {
                              setError(null);
                              const result = await startPreviewAction(u.id);
                              if (result && !result.ok) setError(result.error);
                            })
                          }
                        >
                          👁 Preview
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <CreateUser accounts={accounts} onError={setError} />
    </>
  );
}

function Toggle({
  on,
  disabled,
  label,
  onFlip,
}: {
  on: boolean;
  disabled?: boolean;
  label: string;
  onFlip: (on: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      className={`switch ${on ? "on" : ""}`}
      disabled={disabled}
      onClick={() => onFlip(!on)}
    >
      <i />
    </button>
  );
}

function ResetPassword({
  disabled,
  onReset,
}: {
  disabled?: boolean;
  onReset: (password: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  if (!open) {
    return (
      <button className="act ghost" type="button" disabled={disabled} onClick={() => setOpen(true)}>
        Reset
      </button>
    );
  }
  return (
    <span style={{ display: "inline-flex", gap: 6 }}>
      <input
        className="field"
        style={{ marginBottom: 0, width: 150 }}
        type="text"
        placeholder="New password"
        aria-label="New password"
        value={value}
        onChange={(e) => setValue(e.target.value)}
      />
      <button
        className="act"
        type="button"
        disabled={disabled || value.length < 10}
        onClick={() => {
          onReset(value);
          setOpen(false);
          setValue("");
        }}
      >
        Save
      </button>
    </span>
  );
}

function CreateUser({
  accounts,
  onError,
}: {
  accounts: InstallerAccountRef[];
  onError: (message: string | null) => void;
}) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [form, setForm] = useState({
    name: "", email: "", password: "",
    can_orders: true, can_installer: false, is_admin: false,
    installer_account_id: "",
  });

  const set = (patch: Partial<typeof form>) => setForm({ ...form, ...patch });

  const submit = () =>
    start(async () => {
      onError(null);
      const result = await createUserAction({
        name: form.name,
        email: form.email,
        password: form.password,
        can_orders: form.can_orders,
        can_installer: form.can_installer,
        is_admin: form.is_admin,
        installer_account_id: form.installer_account_id || null,
      });
      if (result.ok) {
        setForm({ name: "", email: "", password: "", can_orders: true,
                  can_installer: false, is_admin: false, installer_account_id: "" });
        router.refresh();
      } else {
        onError(result.error);
      }
    });

  return (
    <div className="panel">
      <h2>Add a user</h2>
      <p>
        Set a starting password of at least 10 characters and pass it on — they
        can&rsquo;t change it themselves yet, but any admin can reset it here.
      </p>
      <div className="form-grid">
        <label className="lbl">Name
          <input className="field" value={form.name} onChange={(e) => set({ name: e.target.value })} />
        </label>
        <label className="lbl">Email
          <input className="field" type="email" value={form.email} onChange={(e) => set({ email: e.target.value })} />
        </label>
        <label className="lbl">Starting password
          <input className="field" type="text" value={form.password} onChange={(e) => set({ password: e.target.value })} />
        </label>
        <label className="lbl">Installer account
          <select
            className="field"
            value={form.installer_account_id}
            onChange={(e) => set({ installer_account_id: e.target.value })}
          >
            <option value="">— none —</option>
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>{a.name}</option>
            ))}
          </select>
        </label>
      </div>
      <div className="check-row">
        <label><input type="checkbox" checked={form.can_orders} onChange={(e) => set({ can_orders: e.target.checked })} /> Orders</label>
        <label><input type="checkbox" checked={form.can_installer} onChange={(e) => set({ can_installer: e.target.checked })} /> Installer portal</label>
        <label><input type="checkbox" checked={form.is_admin} onChange={(e) => set({ is_admin: e.target.checked })} /> Admin</label>
      </div>
      <button
        className="act"
        type="button"
        disabled={pending || !form.name || !form.email || form.password.length < 10}
        onClick={submit}
      >
        {pending ? "Adding…" : "Add user"}
      </button>
    </div>
  );
}
