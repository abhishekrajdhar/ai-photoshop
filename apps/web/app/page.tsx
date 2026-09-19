import Link from "next/link";
import { ArrowRight, Captions, Clapperboard, MessageSquareText, Scissors, Sparkles, Wand2 } from "lucide-react";
import { Logo } from "@/components/layout/logo";
import { Button } from "@/components/ui/button";
import { APP_NAME } from "@/lib/utils";

const FEATURES = [
  { icon: MessageSquareText, title: "Edit by talking", body: "“Remove pauses, tighten the intro, add captions.” The planner turns instructions into reviewable timeline operations." },
  { icon: Scissors, title: "Silence & filler removal", body: "Deterministic detection of dead air, ums and repeated takes — every cut is a reversible operation you can inspect." },
  { icon: Captions, title: "Word-accurate captions", body: "Word timestamps drive SRT, VTT or burned-in captions with social-ready styles." },
  { icon: Clapperboard, title: "Shorts from long-form", body: "Highlight detection with explained scoring factors, auto-reframe to 9:16, jump cuts and smart zooms." },
  { icon: Wand2, title: "Professional timeline", body: "Multi-track, trim handles, split, ripple, undo/redo — and every AI edit is a new version you can compare or restore." },
  { icon: Sparkles, title: "Deterministic rendering", body: "FFmpeg compiles the timeline. The model never touches pixels." },
];

export default function LandingPage() {
  return (
    <div className="relative min-h-screen overflow-hidden">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top,rgba(124,92,255,.22),transparent_50%)]" />
      <header className="relative z-10 flex h-14 items-center justify-between px-6 md:px-10">
        <Logo href="/" />
        <div className="flex items-center gap-2">
          <Button variant="ghost" asChild>
            <Link href="/login">Sign in</Link>
          </Button>
          <Button asChild>
            <Link href="/register">Get started</Link>
          </Button>
        </div>
      </header>
      <section className="relative z-10 mx-auto max-w-5xl px-6 pb-20 pt-20 text-center md:pt-28">
        <div className="mx-auto mb-5 inline-flex items-center gap-2 rounded-full border border-border bg-panel px-3 py-1 text-[11.5px] text-fg-muted">
          <span className="size-1.5 rounded-full bg-success" /> AI-assisted NLE · non-destructive · self-hostable
        </div>
        <h1 className="mx-auto max-w-3xl text-4xl font-semibold tracking-tight md:text-6xl">
          The repetitive half of video editing, <span className="bg-gradient-to-r from-accent to-info bg-clip-text text-transparent">done for you.</span>
        </h1>
        <p className="mx-auto mt-5 max-w-xl text-[15px] text-fg-muted">
          Upload raw footage. Tell {APP_NAME} what you want. Review the proposed cuts on a real timeline, adjust anything, and export.
        </p>
        <div className="mt-8 flex items-center justify-center gap-3">
          <Button size="lg" asChild>
            <Link href="/register">
              Start editing <ArrowRight />
            </Link>
          </Button>
          <Button size="lg" variant="outline" asChild>
            <Link href="/login">I have an account</Link>
          </Button>
        </div>
        <div className="mx-auto mt-14 max-w-3xl rounded-lg border border-border bg-panel p-4 text-left shadow-2xl">
          <div className="mb-3 flex items-center gap-2 text-[11px] uppercase tracking-wider text-fg-subtle">
            <MessageSquareText className="size-3.5" /> AI chat
          </div>
          <div className="space-y-3 text-[13px]">
            <div className="ml-auto w-fit max-w-[80%] rounded-lg bg-accent/20 px-3 py-2">Turn this into a fast-paced 6-minute YouTube video. Remove pauses, filler words and repeated points. Add captions and subtle zooms.</div>
            <div className="w-fit max-w-[85%] rounded-lg bg-elevated px-3 py-2 text-fg-muted">
              I found <span className="text-fg">23 pauses</span> over 0.9 s and <span className="text-fg">41 filler words</span>. Removing them shortens the video by about <span className="text-fg">2 m 12 s</span>. I&apos;ll add 14 emphasis zooms and captions from the transcript.
              <div className="mt-2 flex gap-2">
                <span className="rounded-md bg-accent px-2 py-1 text-[11px] font-medium text-white">Apply changes</span>
                <span className="rounded-md border border-border px-2 py-1 text-[11px]">Preview</span>
                <span className="rounded-md border border-border px-2 py-1 text-[11px]">Show cuts</span>
              </div>
            </div>
          </div>
        </div>
      </section>
      <section className="relative z-10 mx-auto grid max-w-5xl gap-4 px-6 pb-24 md:grid-cols-3">
        {FEATURES.map((f) => (
          <div key={f.title} className="rounded-lg border border-border bg-panel p-4">
            <f.icon className="mb-3 size-5 text-accent" />
            <div className="text-[13.5px] font-semibold">{f.title}</div>
            <div className="mt-1 text-[12.5px] leading-relaxed text-fg-muted">{f.body}</div>
          </div>
        ))}
      </section>
    </div>
  );
}
