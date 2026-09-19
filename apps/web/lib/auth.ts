"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { api, apiGet, apiPost, ApiError } from "@/lib/api";
import type { AuthResponse, User } from "@/lib/types";

export function useUser() {
  return useQuery<User | null>({
    queryKey: ["me"],
    queryFn: async () => {
      try {
        return await apiGet<User>("/auth/me");
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null;
        throw e;
      }
    },
    staleTime: 60_000,
  });
}

export function useLogin() {
  const qc = useQueryClient();
  const router = useRouter();
  return useMutation({
    mutationFn: (body: { email: string; password: string }) => apiPost<AuthResponse>("/auth/login", body),
    onSuccess: (data) => {
      qc.setQueryData(["me"], data.user);
      router.push("/dashboard");
    },
  });
}

export function useRegister() {
  const qc = useQueryClient();
  const router = useRouter();
  return useMutation({
    mutationFn: (body: { email: string; password: string; display_name?: string }) => apiPost<AuthResponse>("/auth/register", body),
    onSuccess: (data) => {
      qc.setQueryData(["me"], data.user);
      router.push("/dashboard");
    },
  });
}

export function useLogout() {
  const qc = useQueryClient();
  const router = useRouter();
  return useMutation({
    mutationFn: () => api<{ ok: boolean }>("/auth/logout", { method: "POST" }),
    onSuccess: () => {
      qc.clear();
      router.push("/login");
    },
  });
}
