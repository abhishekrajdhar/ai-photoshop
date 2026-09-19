"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import type { Page, Project, ProjectSettings } from "@/lib/types";

export function useProjects(includeArchived = false) {
  return useQuery({
    queryKey: ["projects", { includeArchived }],
    queryFn: () => apiGet<Page<Project>>("/projects", { include_archived: includeArchived, limit: 200 }),
  });
}

export function useProject(id: string | undefined) {
  return useQuery({ queryKey: ["project", id], queryFn: () => apiGet<Project>(`/projects/${id}`), enabled: !!id });
}

export function useCreateProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; description?: string; settings?: Partial<ProjectSettings> }) => apiPost<Project>("/projects", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects"] }),
  });
}

export function useUpdateProject(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { name?: string; description?: string; settings?: Partial<ProjectSettings>; status?: "active" | "archived" }) => apiPatch<Project>(`/projects/${id}`, body),
    onSuccess: (p) => {
      qc.setQueryData(["project", id], p);
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}

export function useProjectActions() {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: ["projects"] });
  const archive = useMutation({ mutationFn: (id: string) => apiPost<Project>(`/projects/${id}/archive`), onSuccess: invalidate });
  const restore = useMutation({ mutationFn: (id: string) => apiPatch<Project>(`/projects/${id}`, { status: "active" }), onSuccess: invalidate });
  const duplicate = useMutation({ mutationFn: (id: string) => apiPost<Project>(`/projects/${id}/duplicate`), onSuccess: invalidate });
  const remove = useMutation({ mutationFn: (id: string) => apiDelete<{ ok: boolean }>(`/projects/${id}`), onSuccess: invalidate });
  const rename = useMutation({ mutationFn: ({ id, name }: { id: string; name: string }) => apiPatch<Project>(`/projects/${id}`, { name }), onSuccess: invalidate });
  return { archive, restore, duplicate, remove, rename };
}
