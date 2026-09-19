"use client";
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";
import { TooltipProvider } from "@/components/ui/tooltip";

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = React.useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { staleTime: 10_000, retry: (count, err) => !(err as { status?: number })?.status && count < 2, refetchOnWindowFocus: false },
        },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <TooltipProvider delayDuration={300}>
        {children}
        <Toaster
          theme="dark"
          position="bottom-right"
          toastOptions={{ style: { background: "#1c1e29", border: "1px solid #262836", color: "#e7e8ee", fontSize: 12.5 } }}
        />
      </TooltipProvider>
    </QueryClientProvider>
  );
}
