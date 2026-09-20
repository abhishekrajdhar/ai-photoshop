"use client";
import Link from "next/link";
import { useEffect } from "react";
import { ArrowLeft, Bot, ClapperboardIcon, Download, FileText, History, SlidersHorizontal } from "lucide-react";
import { Logo } from "@/components/layout/logo";
import { JobsIndicator } from "@/components/editor/jobs-indicator";
import { MediaPanel } from "@/components/editor/media-panel";
import { PreviewPanel } from "@/components/editor/preview-panel";
import { TimelinePanel } from "@/components/editor/timeline-panel";
import { RightPanel } from "@/components/editor/right-panel";
import { TranscriptPanel } from "@/components/editor/transcript-panel";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/misc";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useProjectEvents } from "@/lib/events";
import { useProject } from "@/lib/projects";
import { useTimeline } from "@/lib/timeline";
import { useEditorStore, type LeftTab, type RightTab } from "@/stores/editor";

export function Editor({ projectId }: { projectId: string }) {
  const { data: project, isLoading } = useProject(projectId);
  const { leftTab, rightTab, set } = useEditorStore();
  useProjectEvents(projectId);
  useTimeline(projectId);
  useEffect(() => {
    set({ projectId, timelineId: null, selectedClipIds: [], previewSource: { kind: "timeline" } });
  }, [projectId, set]);

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-bg no-select">
      <header className="flex h-11 shrink-0 items-center justify-between border-b border-border px-2">
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="icon-sm" asChild>
            <Link href="/dashboard"><ArrowLeft /></Link>
          </Button>
          <Logo compact />
          {isLoading ? <Skeleton className="h-4 w-40" /> : <span className="text-[13px] font-medium">{project?.name}</span>}
        </div>
        <div className="flex items-center gap-1">
          <JobsIndicator projectId={projectId} />
          <Button variant="ghost" size="sm" onClick={() => set({ rightTab: "versions" })}><History /> History</Button>
          <Button size="sm" onClick={() => set({ rightTab: "export" })}><Download /> Export</Button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        {/* Left: media / transcript */}
        <aside className="flex w-[300px] shrink-0 flex-col border-r border-border bg-panel">
          <Tabs value={leftTab} onValueChange={(v) => set({ leftTab: v as LeftTab })} className="flex min-h-0 flex-1 flex-col">
            <TabsList className="m-2 grid grid-cols-2">
              <TabsTrigger value="media"><ClapperboardIcon /> Media</TabsTrigger>
              <TabsTrigger value="transcript"><FileText /> Transcript</TabsTrigger>
            </TabsList>
            <TabsContent value="media" className="min-h-0 flex-1"><MediaPanel projectId={projectId} /></TabsContent>
            <TabsContent value="transcript" className="min-h-0 flex-1"><TranscriptPanel projectId={projectId} /></TabsContent>
          </Tabs>
        </aside>

        {/* Center: preview */}
        <main className="flex min-w-0 flex-1 flex-col bg-black/30">
          <PreviewPanel projectId={projectId} />
        </main>

        {/* Right: AI chat / inspector */}
        <aside className="flex w-[360px] shrink-0 flex-col border-l border-border bg-panel">
          <Tabs value={rightTab} onValueChange={(v) => set({ rightTab: v as RightTab })} className="flex min-h-0 flex-1 flex-col">
            <TabsList className="m-2 grid grid-cols-4">
              <TabsTrigger value="chat"><Bot /> AI</TabsTrigger>
              <TabsTrigger value="inspector"><SlidersHorizontal /> Inspect</TabsTrigger>
              <TabsTrigger value="versions"><History /> History</TabsTrigger>
              <TabsTrigger value="export"><Download /> Export</TabsTrigger>
            </TabsList>
            <TabsContent value={rightTab} className="min-h-0 flex-1"><RightPanel projectId={projectId} tab={rightTab} /></TabsContent>
          </Tabs>
        </aside>
      </div>

      {/* Bottom: timeline */}
      <section className="h-[300px] shrink-0 border-t border-border bg-panel">
        <TimelinePanel projectId={projectId} />
      </section>
    </div>
  );
}
