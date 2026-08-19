"use server";

import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";
import {
  authBootstrap,
  authLogin,
  authLogout,
  type AuthUser,
} from "@/lib/api";
import { homeFor, SESSION_COOKIE } from "@/lib/auth";

type FormState = { error: string } | null;

async function startSession(result: { token: string; user: AuthUser }) {
  const jar = await cookies();
  jar.set(SESSION_COOKIE, result.token, {
    httpOnly: true,
    secure: process.env.NODE_ENV !== "development",
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60 * 24 * 30,
  });
  redirect(homeFor(result.user));
}

async function agent(): Promise<string> {
  const h = await headers();
  return h.get("user-agent") ?? "";
}

export async function signIn(_prev: FormState, form: FormData): Promise<FormState> {
  const email = String(form.get("email") ?? "");
  const password = String(form.get("password") ?? "");
  if (!email || !password) return { error: "Enter your email and password." };
  let result;
  try {
    result = await authLogin({ email, password, user_agent: await agent() });
  } catch (error) {
    return { error: error instanceof Error ? error.message : "Sign-in failed." };
  }
  await startSession(result);
  return null;
}

export async function createFirstAdmin(
  _prev: FormState,
  form: FormData,
): Promise<FormState> {
  const name = String(form.get("name") ?? "");
  const email = String(form.get("email") ?? "");
  const password = String(form.get("password") ?? "");
  const setupKey = String(form.get("setup_key") ?? "");
  if (!setupKey) return { error: "Enter the SETUP_KEY from your Vercel environment variables." };
  let result;
  try {
    result = await authBootstrap({
      name,
      email,
      password,
      setup_key: setupKey,
      user_agent: await agent(),
    });
  } catch (error) {
    return { error: error instanceof Error ? error.message : "Could not create the admin." };
  }
  await startSession(result);
  return null;
}

export async function signOut(): Promise<void> {
  const jar = await cookies();
  const token = jar.get(SESSION_COOKIE)?.value;
  if (token) await authLogout(token);
  jar.delete(SESSION_COOKIE);
  redirect("/login");
}
