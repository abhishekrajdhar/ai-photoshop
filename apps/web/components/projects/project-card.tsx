"use client";
import Link from "next/link";
import { useState } from "react";
import { Archive, ArchiveRestore, Copy, Film, MoreHorizontal, Pencil, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/misc";
import { useProjectActions } from "@/lib/projects";
import type { Project } from "@/lib/types";
import { relativeTime } from "@/lib/utils";
import { PLATFORM_LABEL } from "@/lib/platforms";


export function ProjectCard({ project }: { project: Project }) {
  const actions = useProjectActions();
  const [renaming, setRenaming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [name, setName] = useState(project.name);
  const archived = project.status === "archived";
  return (
    <div className="group relative flex flex-col overflow-hidden rounded-lg border border-border bg-panel transition-colors hover:border-border-strong">
      <Link href={`/projects/${project.id}`} className="block">
        <div className="relative aspect-video w-full bg-panel-2">
          {project.thumbnail_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={project.thumbnail_url} alt="" className="size-full object-cover" />
          ) : (
            <div className="flex size-full items-center justify-center text-fg-subtle">
              <Film className="size-7" />
            </div>
          )}
          <div className="absolute left-2 top-2 flex gap-1">
            <Badge variant="secondary">{PLATFORM_LABEL[project.settings.target_platform] ?? "Generic"}</Badge>
            {archived && <Badge variant="warning">Archived</Badge>}
          </div>
        </div>
      </Link>
      <div className="flex items-start justify-between gap-2 p-3">
        <div className="min-w-0">
          <Link href={`/projects/${project.id}`} className="block truncate text-[13px] font-medium hover:underline">{project.name}</Link>
          <div className="mt-0.5 text-[11.5px] text-fg-subtle">
            {project.asset_count} {project.asset_count === 1 ? "clip" : "clips"} · edited {relativeTime(project.updated_at)}
          </div>
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon-sm" className="opacity-0 group-hover:opacity-100 data-[state=open]:opacity-100">
              <MoreHorizontal />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={() => setRenaming(true)}><Pencil /> Rename</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => actions.duplicate.mutate(project.id, { onSuccess: () => toast.success("Project duplicated") })}><Copy /> Duplicate</DropdownMenuItem>
            {archived ? (
              <DropdownMenuItem onSelect={() => actions.restore.mutate(project.id)}><ArchiveRestore /> Restore</DropdownMenuItem>
            ) : (
              <DropdownMenuItem onSelect={() => actions.archive.mutate(project.id)}><Archive /> Archive</DropdownMenuItem>
            )}
            <DropdownMenuSeparator />
            <DropdownMenuItem destructive onSelect={() => setDeleting(true)}><Trash2 /> Delete</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      <Dialog open={renaming} onOpenChange={setRenaming}>
        <DialogContent className="max-w-sm">
          <DialogHeader><DialogTitle>Rename project</DialogTitle></DialogHeader>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              actions.rename.mutate({ id: project.id, name }, { onSuccess: () => setRenaming(false) });
            }}
          >
            <Input value={name} onChange={(e) => setName(e.target.value)} autoFocus />
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => setRenaming(false)}>Cancel</Button>
              <Button type="submit" loading={actions.rename.isPending}>Save</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={deleting} onOpenChange={setDeleting}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Delete “{project.name}”?</DialogTitle>
            <DialogDescription>This permanently removes the project, its media, transcripts and renders. Original files you uploaded elsewhere are unaffected.</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDeleting(false)}>Cancel</Button>
            <Button variant="destructive" loading={actions.remove.isPending} onClick={() => actions.remove.mutate(project.id, { onSuccess: () => { setDeleting(false); toast.success("Project deleted"); } })}>Delete</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
