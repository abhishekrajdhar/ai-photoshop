"use client";
import { useEffect, useMemo } from "react";
import { Activity, AlertCircle, CheckCircle2, Loader2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger, Progress } from "@/components/ui/misc";
import { apiGet, apiPost } from "@/lib/api";
import type { Job } from "@/lib/types";
import { JOB_LABEL, useJobsStore } from "@/stores/jobs";
import { cn } from "@/lib/utils";

export function JobsIndicator({ projectId }: { projectId: string }) {
  const allJobs = useJobsStore((s) => s.jobs);
  const jobs = useMemo(() => Object.values(allJobs).filter((j) => j.project_id === projectId).sort((a, b) => b.updatedAt - a.updatedAt), [allJobs, projectId]);
  const upsertMany = useJobsStore((s) => s.upsertMany);
  useEffect(() => {
    apiGet<Job[]>("/jobs", { project_id: projectId, limit: 30 }).then(upsertMany).catch(() => undefined);
  }, [projectId, upsertMany]);
  const active = jobs.filter((j) => j.status === "QUEUED" || j.status === "RUNNING");
  const failed = jobs.filter((j) => j.status === "FAILED");
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="sm" className={cn("gap-2", active.length && "text-accent")}>
          {active.length ? <Loader2 className="animate-spin" /> : failed.length ? <AlertCircle className="text-danger" /> : <Activity />}
          {active.length ? `${active.length} running` : "Jobs"}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 p-0">
        <div className="panel-header border-b">Background jobs</div>
        <div className="max-h-80 overflow-y-auto">
          {jobs.length === 0 && <div className="p-4 text-center text-[12px] text-fg-subtle">No jobs yet.</div>}
          {jobs.slice(0, 20).map((j) => (
            <div key={j.id} className="border-b border-border px-3 py-2 last:border-0">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-1.5 text-[12px]">
                  {j.status === "RUNNING" || j.status === "QUEUED" ? <Loader2 className="size-3 animate-spin text-accent" /> : j.status === "COMPLETED" ? <CheckCircle2 className="size-3 text-success" /> : <AlertCircle className="size-3 text-danger" />}
                  <span className="font-medium">{JOB_LABEL[j.type] ?? j.type}</span>
                </div>
                {(j.status === "RUNNING" || j.status === "QUEUED") && (
                  <Button variant="ghost" size="icon-xs" onClick={() => apiPost(`/jobs/${j.id}/cancel`)} title="Cancel">
                    <X />
                  </Button>
                )}
              </div>
              {(j.status === "RUNNING" || j.status === "QUEUED") && <Progress className="mt-1.5" value={j.progress * 100} />}
              <div className="mt-1 truncate text-[11px] text-fg-subtle">{j.error ?? j.message ?? (j.meta.filename as string) ?? ""}</div>
            </div>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
}
