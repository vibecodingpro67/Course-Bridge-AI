"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";

const universities = ["UC Berkeley", "UCLA", "UC San Diego", "UC Irvine", "UC Davis", "UC Santa Barbara"];
const colleges = ["City College of San Francisco", "De Anza College", "Santa Monica College", "Diablo Valley College", "Foothill College"];
const majors = ["Computer Science", "Business Administration", "Economics", "Data Science", "Psychology", "Engineering", "Biology"];

type Profile = { firstName: string; college: string; university: string; major: string; courses: string };

const stepCopy = [
  ["Let’s get started", "What should we call you?", "A few details help us make your transfer plan feel personal."],
  ["Your starting point", "Where are you taking classes now?", "We’ll use your college to find the right course pathways."],
  ["Your destination", "Where do you want to transfer?", "Choose the university you’re working toward first. You can add more later."],
  ["Your direction", "What do you want to study?", "Your major helps us focus the plan on the courses that matter most."],
  ["Your progress", "Which courses have you completed?", "Add courses separated by commas. It’s okay if you’re just getting started."],
  ["Your path is ready", "A clearer route to your transfer goal.", "Here’s a starting point based on what you shared. You can refine it anytime."],
];

export default function OnboardingClient() {
  const router = useRouter();
  const [step, setStep] = useState(1);
  const [profile, setProfile] = useState<Profile>({ firstName: "", college: "", university: "", major: "", courses: "" });

  const current = stepCopy[step - 1];
  const update = (key: keyof Profile, value: string) => setProfile((previous) => ({ ...previous, [key]: value }));
  const canContinue = step === 6 || Boolean(profile[(["firstName", "college", "university", "major", "courses"] as const)[step - 1]].trim());
  const courseList = useMemo(() => profile.courses.split(",").map((course) => course.trim()).filter(Boolean), [profile.courses]);

  function next() { if (canContinue) setStep((value) => Math.min(6, value + 1)); }
  function back() { setStep((value) => Math.max(1, value - 1)); }

  return (
    <main className="cb-shell min-h-screen">
      <header className="cb-header">
        <a href="/" className="cb-brand" aria-label="CourseBridge AI home"><span className="cb-brand-mark">C</span><span>CourseBridge <em>AI</em></span></a>
        <div className="hidden items-center gap-3 sm:flex"><div className="cb-progress"><span style={{ width: `${(step / 6) * 100}%` }} /></div><span className="text-sm font-medium text-slate-500">Step {step} of 6</span></div>
        <span className="text-sm font-medium text-slate-500 sm:hidden">{step}/6</span>
      </header>

      <div className="mx-auto flex min-h-[calc(100vh-73px)] w-full max-w-6xl items-center px-6 py-12 sm:px-10 lg:px-16">
        <div className="grid w-full gap-12 lg:grid-cols-[minmax(260px,0.8fr)_minmax(380px,1.2fr)] lg:gap-24">
          <div className="self-center">
            <div className="mb-7 flex items-center gap-2 sm:hidden"><div className="cb-progress flex-1"><span style={{ width: `${(step / 6) * 100}%` }} /></div><span className="text-xs text-slate-400">{step}/6</span></div>
            <p className="cb-kicker">{current[0]}</p>
            <h1 className="mt-4 max-w-md text-4xl font-semibold leading-[1.08] tracking-[-0.03em] text-slate-950 sm:text-5xl">{step === 1 && profile.firstName ? `Nice to meet you, ${profile.firstName}.` : current[1]}</h1>
            <p className="mt-5 max-w-sm text-base leading-7 text-slate-500">{current[2]}</p>
            {step < 6 && <p className="mt-10 hidden text-sm text-slate-400 lg:block">You can always update these details later.</p>}
          </div>

          <div className="self-center">
            <div className="min-h-[285px] rounded-3xl border border-slate-200 bg-white p-6 shadow-[0_20px_70px_rgba(30,64,110,0.07)] sm:p-9">
              {step === 1 && <TextField label="First name" value={profile.firstName} onChange={(value) => update("firstName", value)} placeholder="e.g. Maya" autoFocus />}
              {step === 2 && <ChoiceField label="Community college" value={profile.college} onChange={(value) => update("college", value)} options={colleges} placeholder="Search colleges" />}
              {step === 3 && <ChoiceField label="Target university" value={profile.university} onChange={(value) => update("university", value)} options={universities} placeholder="Search universities" />}
              {step === 4 && <ChoiceField label="Intended major" value={profile.major} onChange={(value) => update("major", value)} options={majors} placeholder="Search majors" />}
              {step === 5 && <div><label className="cb-label" htmlFor="courses">Completed courses</label><textarea id="courses" autoFocus value={profile.courses} onChange={(event) => update("courses", event.target.value)} placeholder="e.g. English 1A, Calculus 1, Econ 1" rows={5} className="cb-input resize-none" /><p className="mt-3 text-xs text-slate-400">Separate each course with a comma.</p></div>}
              {step === 6 && <PlanPreview profile={profile} courses={courseList} />}
            </div>

            <div className="mt-7 flex items-center justify-between">
              {step > 1 ? <button onClick={back} className="cb-secondary">← Back</button> : <span />}
              {step < 6 ? <button onClick={next} disabled={!canContinue} className="cb-primary disabled:cursor-not-allowed disabled:opacity-40">Continue <span aria-hidden>→</span></button> : <button onClick={() => router.push("/")} className="cb-primary">Open my dashboard <span aria-hidden>→</span></button>}
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}

function TextField({ label, value, onChange, placeholder, autoFocus }: { label: string; value: string; onChange: (value: string) => void; placeholder: string; autoFocus?: boolean }) {
  return <div><label className="cb-label" htmlFor="onboarding-input">{label}</label><input id="onboarding-input" autoFocus={autoFocus} value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} className="cb-input" /></div>;
}

function ChoiceField({ label, value, onChange, options, placeholder }: { label: string; value: string; onChange: (value: string) => void; options: string[]; placeholder: string }) {
  return <div><label className="cb-label" htmlFor="choice-input">{label}</label><input id="choice-input" list="choice-options" autoFocus value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} className="cb-input" /><datalist id="choice-options">{options.map((option) => <option key={option} value={option} />)}</datalist><div className="mt-5 flex flex-wrap gap-2">{options.slice(0, 4).map((option) => <button type="button" key={option} onClick={() => onChange(option)} className={`rounded-full border px-3 py-2 text-xs transition ${value === option ? "border-blue-600 bg-blue-50 font-semibold text-blue-700" : "border-slate-200 text-slate-500 hover:border-blue-300 hover:text-blue-600"}`}>{option}</button>)}</div></div>;
}

function PlanPreview({ profile, courses }: { profile: Profile; courses: string[] }) {
  const recommended = profile.major.toLowerCase().includes("computer") || profile.major.toLowerCase().includes("data") ? ["Calculus II", "Data Structures", "Discrete Mathematics"] : ["Major preparation course", "Critical thinking / English", "Statistics"];
  return <div><div className="flex items-start justify-between gap-4"><div><p className="text-sm font-semibold text-slate-900">{profile.university}</p><p className="mt-1 text-sm text-slate-500">{profile.major}</p></div><span className="rounded-full bg-blue-50 px-3 py-1 text-xs font-semibold text-blue-700">Starter plan</span></div><div className="mt-7 grid gap-3 sm:grid-cols-2"><div className="rounded-2xl bg-slate-50 p-4"><p className="text-xs font-medium uppercase tracking-wider text-slate-400">Completed</p><p className="mt-2 text-2xl font-semibold text-slate-900">{courses.length || 0}</p><p className="mt-1 text-xs text-slate-500">courses captured</p></div><div className="rounded-2xl bg-blue-50 p-4"><p className="text-xs font-medium uppercase tracking-wider text-blue-500">Next up</p><p className="mt-2 text-2xl font-semibold text-slate-900">{recommended.length}</p><p className="mt-1 text-xs text-slate-500">recommended courses</p></div></div><div className="mt-6"><p className="text-xs font-semibold uppercase tracking-wider text-slate-400">Suggested starting sequence</p><div className="mt-3 space-y-2">{recommended.map((course, index) => <div key={course} className="flex items-center gap-3 rounded-xl border border-slate-100 px-3 py-2.5 text-sm text-slate-700"><span className="flex h-6 w-6 items-center justify-center rounded-full bg-blue-50 text-xs font-semibold text-blue-600">{index + 1}</span>{course}</div>)}</div></div></div>;
}
