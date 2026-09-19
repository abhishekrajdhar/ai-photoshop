"use client";
import Link from "next/link";
import { useState } from "react";
import { FolderOpen, Plus, Search } from "lucide-react";
import { AppShell } from "@/components/layout/app-shell";
import { ProjectCard } from "@/components/projects/project-card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { EmptyState, Skeleton } from "@/components/ui/misc";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { useProjects } from "@/lib/projects";

export default function DashboardPage() {
  const [showArchived, setShowArchived] = useState(false);
  const [query, setQuery] = useState("");
  const { data, isLoading, error } = useProjects(showArchived);
  const items = (data?.items ?? []).filter((p) => p.name.toLowerCase().includes(query.toLowerCase()));
  return (
    <AppShell>
      <div className="mx-auto max-w-6xl px-6 py-8">
        <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">Projects</h1>
            <p className="text-[12.5px] text-fg-muted">{data ? `${data.total} project${data.total === 1 ? "" : "s"}` : " "}</p>
          </div>
          <div className="flex items-center gap-3">
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-2 size-3.5 text-fg-subtle" />
              <Input className="w-56 pl-8" placeholder="Search projects…" value={query} onChange={(e) => setQuery(e.target.value)} />
            </div>
            <div className="flex items-center gap-2">
              <Switch id="archived" checked={showArchived} onCheckedChange={setShowArchived} />
              <Label htmlFor="archived">Show archived</Label>
            </div>
            <Button asChild>
              <Link href="/projects/new"><Plus /> New project</Link>
            </Button>
          </div>
        </div>
        {error && <div className="rounded-md border border-danger/30 bg-danger/10 p-3 text-[12.5px] text-danger">Failed to load projects: {(error as Error).message}</div>}
        {isLoading ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="aspect-[4/3.3]" />
            ))}
          </div>
        ) : items.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border">
            <EmptyState
              icon={<FolderOpen />}
              title={query ? "No projects match your search" : "No projects yet"}
              description="Create a project, upload footage, and let the AI propose the first cut."
              action={
                <Button asChild>
                  <Link href="/projects/new"><Plus /> Create your first project</Link>
                </Button>
              }
            />
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {items.map((p) => (
              <ProjectCard key={p.id} project={p} />
            ))}
          </div>
        )}
      </div>
    </AppShell>
  );
}
