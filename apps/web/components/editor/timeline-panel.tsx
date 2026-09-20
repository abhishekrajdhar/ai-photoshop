"use client";
import { Timeline } from "@/components/timeline/timeline";

export function TimelinePanel({ projectId }: { projectId: string }) {
  return <Timeline projectId={projectId} />;
}
