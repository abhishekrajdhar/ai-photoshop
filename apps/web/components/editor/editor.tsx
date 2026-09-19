"use client";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { Logo } from "@/components/layout/logo";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/misc";
import { useProject } from "@/lib/projects";

/** Editor shell — panels are filled in by the media, timeline, and AI modules. */
export function Editor({ projectId }: { projectId: string }) {
  const { data: project, isLoading } = useProject(projectId);
  return (
    <div className="flex h-screen flex-col bg-bg">
      <header className="flex h-11 items-center justify-between border-b border-border px-3">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="icon-sm" asChild>
            <Link href="/dashboard"><ArrowLeft /></Link>
          </Button>
          <Logo compact />
          {isLoading ? <Skeleton className="h-4 w-40" /> : <span className="text-[13px] font-medium">{project?.name}</span>}
        </div>
      </header>
      <div className="flex flex-1 items-center justify-center text-[12.5px] text-fg-muted">Editor panels load here.</div>
    </div>
  );
}
