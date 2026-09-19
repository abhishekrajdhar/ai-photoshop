"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ArrowRight } from "lucide-react";
import { AppShell } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useCreateProject } from "@/lib/projects";
import type { TargetPlatform } from "@/lib/types";
import { PLATFORMS } from "@/lib/platforms";
import { cn } from "@/lib/utils";


export default function NewProjectPage() {
  const router = useRouter();
  const create = useCreateProject();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [platform, setPlatform] = useState<TargetPlatform>("youtube");
  const [aspect, setAspect] = useState("16:9");
  const selected = PLATFORMS.find((p) => p.id === platform)!;
  return (
    <AppShell>
      <div className="mx-auto max-w-2xl px-6 py-10">
        <h1 className="text-xl font-semibold tracking-tight">New project</h1>
        <p className="mt-1 text-[12.5px] text-fg-muted">Choose where this video will live. You can change this later, and create Shorts from any project.</p>
        <form
          className="mt-8 space-y-6"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate({ name, description, settings: { target_platform: platform, aspect_ratio: aspect } }, { onSuccess: (p) => router.push(`/projects/${p.id}`) });
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor="name">Project name</Label>
            <Input id="name" required autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Episode 12 — AI in production" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="desc">Description <span className="text-fg-subtle">(optional, helps the AI understand context)</span></Label>
            <Textarea id="desc" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="A 40-minute interview with a founder about scaling infrastructure…" />
          </div>
          <div className="space-y-2">
            <Label>Target platform</Label>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {PLATFORMS.map((p) => (
                <button
                  type="button"
                  key={p.id}
                  onClick={() => {
                    setPlatform(p.id);
                    setAspect(p.aspect);
                  }}
                  className={cn(
                    "rounded-md border px-3 py-2 text-left transition-colors hover:border-border-strong",
                    platform === p.id ? "border-accent bg-accent/10" : "border-border bg-panel",
                  )}
                >
                  <div className="text-[12.5px] font-medium">{p.label}</div>
                  <div className="text-[11px] text-fg-subtle">{p.aspect}</div>
                </button>
              ))}
            </div>
            <p className="text-[11.5px] text-fg-subtle">{selected.hint}</p>
          </div>
          <div className="space-y-1.5">
            <Label>Sequence aspect ratio</Label>
            <Select value={aspect} onValueChange={setAspect}>
              <SelectTrigger className="w-40"><SelectValue /></SelectTrigger>
              <SelectContent>
                {["16:9", "9:16", "1:1", "4:5", "4:3"].map((a) => (
                  <SelectItem key={a} value={a}>{a}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {create.error && <div className="rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-[12px] text-danger">{(create.error as Error).message}</div>}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => router.back()}>Cancel</Button>
            <Button type="submit" loading={create.isPending}>Create project <ArrowRight /></Button>
          </div>
        </form>
      </div>
    </AppShell>
  );
}
