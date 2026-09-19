"use client";
import Link from "next/link";
import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { AuthCard } from "@/components/layout/auth-card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, apiPost } from "@/lib/api";

function ResetForm() {
  const params = useSearchParams();
  const router = useRouter();
  const token = params.get("token") ?? "";
  const [password, setPassword] = useState("");
  const reset = useMutation({
    mutationFn: () => apiPost<{ ok: boolean }>("/auth/password-reset/confirm", { token, password }),
    onSuccess: () => {
      toast.success("Password updated. Please sign in.");
      router.push("/login");
    },
  });
  const error = reset.error instanceof ApiError ? reset.error.message : null;
  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        reset.mutate();
      }}
    >
      <div className="space-y-1.5">
        <Label htmlFor="password">New password</Label>
        <Input id="password" type="password" minLength={8} required value={password} onChange={(e) => setPassword(e.target.value)} />
      </div>
      {error && <div className="rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-[12px] text-danger">{error}</div>}
      <Button type="submit" className="w-full" loading={reset.isPending} disabled={!token}>Set new password</Button>
    </form>
  );
}

export default function ResetPasswordPage() {
  return (
    <AuthCard title="Choose a new password" footer={<Link href="/login" className="text-accent hover:underline">Back to sign in</Link>}>
      <Suspense>
        <ResetForm />
      </Suspense>
    </AuthCard>
  );
}
