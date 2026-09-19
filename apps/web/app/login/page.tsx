"use client";
import Link from "next/link";
import { useState } from "react";
import { AuthCard } from "@/components/layout/auth-card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useLogin } from "@/lib/auth";
import { ApiError } from "@/lib/api";

export default function LoginPage() {
  const login = useLogin();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const error = login.error instanceof ApiError ? login.error.message : login.error ? "Something went wrong" : null;
  return (
    <AuthCard
      title="Welcome back"
      subtitle="Sign in to your projects."
      footer={
        <>
          New here? <Link href="/register" className="text-accent hover:underline">Create an account</Link>
        </>
      }
    >
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          login.mutate({ email, password });
        }}
      >
        <div className="space-y-1.5">
          <Label htmlFor="email">Email</Label>
          <Input id="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <Label htmlFor="password">Password</Label>
            <Link href="/forgot-password" className="text-[11.5px] text-fg-muted hover:text-fg">Forgot password?</Link>
          </div>
          <Input id="password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>
        {error && <div className="rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-[12px] text-danger">{error}</div>}
        <Button type="submit" className="w-full" loading={login.isPending}>Sign in</Button>
      </form>
    </AuthCard>
  );
}
