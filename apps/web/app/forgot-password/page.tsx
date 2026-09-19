"use client";
import Link from "next/link";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { AuthCard } from "@/components/layout/auth-card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiPost } from "@/lib/api";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const request = useMutation({
    mutationFn: () => apiPost<{ ok: boolean; dev_reset_token: string | null }>("/auth/password-reset/request", { email }),
  });
  return (
    <AuthCard title="Reset your password" subtitle="We'll issue a one-hour reset link." footer={<Link href="/login" className="text-accent hover:underline">Back to sign in</Link>}>
      {request.isSuccess ? (
        <div className="space-y-3 text-[12.5px] text-fg-muted">
          <p>If an account exists for <span className="text-fg">{email}</span>, a reset link has been issued.</p>
          {request.data.dev_reset_token && (
            <div className="rounded-md border border-warning/30 bg-warning/10 p-3">
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-warning">Development mode</div>
              No email provider is configured, so here is your link:
              <div className="mt-2">
                <Link className="text-accent underline" href={`/reset-password?token=${request.data.dev_reset_token}`}>Open reset link</Link>
              </div>
            </div>
          )}
        </div>
      ) : (
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            request.mutate();
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor="email">Email</Label>
            <Input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <Button type="submit" className="w-full" loading={request.isPending}>Send reset link</Button>
        </form>
      )}
    </AuthCard>
  );
}
