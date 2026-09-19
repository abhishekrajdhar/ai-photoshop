"use client";
import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { AppShell } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/misc";
import { ApiError, apiPatch, apiPost } from "@/lib/api";
import { useUser } from "@/lib/auth";
import type { User } from "@/lib/types";

export default function SettingsPage() {
  const qc = useQueryClient();
  const { data: user } = useUser();
  const [name, setName] = useState("");
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  useEffect(() => {
    if (user) setName(user.display_name);
  }, [user]);
  const profile = useMutation({
    mutationFn: () => apiPatch<User>("/auth/me", { display_name: name }),
    onSuccess: (u) => {
      qc.setQueryData(["me"], u);
      toast.success("Profile updated");
    },
  });
  const password = useMutation({
    mutationFn: () => apiPost<{ ok: boolean }>("/auth/change-password", { current_password: current, new_password: next }),
    onSuccess: () => {
      setCurrent("");
      setNext("");
      toast.success("Password changed");
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed to change password"),
  });
  return (
    <AppShell>
      <div className="mx-auto max-w-2xl px-6 py-10">
        <h1 className="text-xl font-semibold tracking-tight">Account settings</h1>
        <section className="mt-8 space-y-4">
          <h2 className="text-[13px] font-semibold">Profile</h2>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label>Email</Label>
              <Input value={user?.email ?? ""} disabled />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="dn">Display name</Label>
              <Input id="dn" value={name} onChange={(e) => setName(e.target.value)} />
            </div>
          </div>
          <Button onClick={() => profile.mutate()} loading={profile.isPending} disabled={!user || name === user.display_name}>Save profile</Button>
        </section>
        <Separator className="my-8" />
        <section className="space-y-4">
          <h2 className="text-[13px] font-semibold">Password</h2>
          <form
            className="grid gap-4 sm:grid-cols-2"
            onSubmit={(e) => {
              e.preventDefault();
              password.mutate();
            }}
          >
            <div className="space-y-1.5">
              <Label htmlFor="cur">Current password</Label>
              <Input id="cur" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="new">New password</Label>
              <Input id="new" type="password" autoComplete="new-password" minLength={8} value={next} onChange={(e) => setNext(e.target.value)} required />
            </div>
            <div className="sm:col-span-2">
              <Button type="submit" variant="secondary" loading={password.isPending}>Change password</Button>
            </div>
          </form>
        </section>
        <Separator className="my-8" />
        <section className="space-y-2">
          <h2 className="text-[13px] font-semibold">AI providers</h2>
          <p className="text-[12.5px] text-fg-muted">
            API keys are configured server-side via environment variables (<code className="text-mono text-fg">OPENAI_API_KEY</code>, <code className="text-mono text-fg">ANTHROPIC_API_KEY</code>) and are never sent to the browser.
          </p>
        </section>
      </div>
    </AppShell>
  );
}
