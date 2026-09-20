"use client";
import { FileText } from "lucide-react";
import { EmptyState } from "@/components/ui/misc";

export function TranscriptPanel({ projectId }: { projectId: string }) {
  void projectId;
  return <EmptyState icon={<FileText />} title="Transcript" description="Transcribe your footage to edit by text." />;
}
