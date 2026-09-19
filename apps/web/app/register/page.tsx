"use client";
import Link from "next/link";
import { useState } from "react";
import { AuthCard } from "@/components/layout/auth-card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useRegister } from "@/lib/auth";
import { ApiError } from "@/lib/api";

export default function RegisterPage() {
  const register = useRegister();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const error = register.error instanceof ApiError ? register.error.message : register.error ? "Something went wrong" : null;
  return (
    <AuthCard
      title="Create your account"
      subtitle="Free during development — bring your own AI keys."
      footer={
        <>
          Already have an account? <Link href="/login" className="text-accent hover:underline">Sign in</Link>
        </>
      }
    >
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          register.mutate({ email, password, display_name: name });
        }}
      >
        <div className="space-y-1.5">
          <Label htmlFor="name">Name</Label>
          <Input id="name" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Optional" />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="email">Email</Label>
          <Input id="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="password">Password</Label>
          <Input id="password" type="password" autoComplete="new-password" minLength={8} required value={password} onChange={(e) => setPassword(e.target.value)} placeholder="At least 8 characters" />
        </div>
        {error && <div className="rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-[12px] text-danger">{error}</div>}
        <Button type="submit" className="w-full" loading={register.isPending}>Create account</Button>
      </form>
    </AuthCard>
  );
}
