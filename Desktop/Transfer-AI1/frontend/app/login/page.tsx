"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  function continueToOnboarding(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    router.push("/onboarding");
  }

  return (
    <main className="cb-shell flex min-h-screen flex-col">
      <header className="cb-header">
        <a href="/" className="cb-brand" aria-label="CourseBridge AI home">
          <span className="cb-brand-mark">C</span>
          <span>CourseBridge <em>AI</em></span>
        </a>
        <p className="hidden text-sm text-slate-500 sm:block">Transfer planning, made clearer.</p>
      </header>

      <section className="flex flex-1 items-center justify-center px-6 py-16">
        <div className="w-full max-w-[420px]">
          <div className="mb-9 text-center">
            <p className="cb-kicker">Welcome back</p>
            <h1 className="mt-3 text-3xl font-semibold tracking-tight text-slate-950">Sign in to your plan</h1>
            <p className="mt-3 text-[15px] leading-6 text-slate-500">Pick up where you left off and keep your transfer path moving.</p>
          </div>

          <form onSubmit={continueToOnboarding} className="rounded-3xl border border-slate-200 bg-white p-7 shadow-[0_18px_50px_rgba(30,64,110,0.06)] sm:p-8">
            <label className="cb-label" htmlFor="email">Email address</label>
            <input id="email" required type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@example.com" className="cb-input" />
            <div className="mt-5 flex items-center justify-between">
              <label className="cb-label mb-0" htmlFor="password">Password</label>
              <button type="button" className="text-xs font-medium text-blue-600 hover:text-blue-700">Forgot password?</button>
            </div>
            <input id="password" required type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="••••••••" className="cb-input" />
            <button type="submit" className="cb-primary mt-6 w-full">Continue to CourseBridge <span aria-hidden>→</span></button>
            <div className="my-6 flex items-center gap-3 text-xs text-slate-400"><span className="h-px flex-1 bg-slate-200" />or<span className="h-px flex-1 bg-slate-200" /></div>
            <button type="button" onClick={() => router.push("/onboarding")} className="flex w-full items-center justify-center gap-3 rounded-xl border border-slate-200 px-4 py-3 text-sm font-semibold text-slate-700 transition hover:border-slate-300 hover:bg-slate-50">
              <span className="text-base font-bold text-blue-600">G</span> Continue with Google
            </button>
          </form>
          <p className="mt-6 text-center text-xs leading-5 text-slate-400">Demo mode is active — sign in continues to onboarding.</p>
        </div>
      </section>
    </main>
  );
}
