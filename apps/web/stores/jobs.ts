import { create } from "zustand";
import type { Job, JobStatus } from "@/lib/types";

export interface JobLite {
  id: string;
  project_id: string | null;
  type: string;
  status: JobStatus;
  progress: number;
  message: string;
  error: string | null;
  result: Record<string, unknown>;
  meta: Record<string, unknown>;
  updatedAt: number;
}

interface JobsState {
  jobs: Record<string, JobLite>;
  upsert: (job: Partial<JobLite> & { id: string }) => void;
  upsertMany: (jobs: Job[]) => void;
  remove: (id: string) => void;
}

export const useJobsStore = create<JobsState>((set) => ({
  jobs: {},
  upsert: (job) =>
    set((s) => ({
      jobs: {
        ...s.jobs,
        [job.id]: {
          ...(s.jobs[job.id] ?? { project_id: null, type: "JOB", status: "QUEUED", progress: 0, message: "", error: null, result: {}, meta: {} }),
          ...job,
          updatedAt: Date.now(),
        } as JobLite,
      },
    })),
  upsertMany: (jobs) =>
    set((s) => {
      const next = { ...s.jobs };
      for (const j of jobs) {
        next[j.id] = { id: j.id, project_id: j.project_id, type: j.type, status: j.status, progress: j.progress, message: j.message, error: j.error, result: j.result, meta: j.meta, updatedAt: Date.now() };
      }
      return { jobs: next };
    }),
  remove: (id) =>
    set((s) => {
      const next = { ...s.jobs };
      delete next[id];
      return { jobs: next };
    }),
}));

export const selectProjectJobs = (projectId: string) => (s: JobsState) =>
  Object.values(s.jobs)
    .filter((j) => j.project_id === projectId)
    .sort((a, b) => b.updatedAt - a.updatedAt);

export const JOB_LABEL: Record<string, string> = {
  UPLOAD_PROCESSING: "Processing upload",
  PROXY_GENERATION: "Generating proxy",
  TRANSCRIPTION: "Transcribing",
  SCENE_DETECTION: "Detecting scenes",
  AUDIO_ANALYSIS: "Analyzing audio",
  VISION_ANALYSIS: "Analyzing visuals",
  CONTENT_ANALYSIS: "Analyzing content",
  EDIT_PLANNING: "Planning edit",
  HIGHLIGHT_DETECTION: "Finding highlights",
  SHORT_GENERATION: "Generating Shorts",
  THUMBNAIL_GENERATION: "Generating thumbnails",
  REFRAME_TRACKING: "Tracking subject",
  RENDERING: "Rendering",
  EXPORT: "Exporting",
};
