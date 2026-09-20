"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutGrid, LogOut, Settings, User as UserIcon } from "lucide-react";
import { Logo } from "@/components/layout/logo";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { useLogout, useRequireAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { user } = useRequireAuth();
  const logout = useLogout();
  const nav = [
    { href: "/dashboard", label: "Projects", icon: LayoutGrid },
    { href: "/settings", label: "Settings", icon: Settings },
  ];
  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-40 flex h-12 items-center justify-between border-b border-border bg-bg/80 px-5 backdrop-blur">
        <div className="flex items-center gap-6">
          <Logo />
          <nav className="flex items-center gap-1">
            {nav.map((n) => (
              <Link
                key={n.href}
                href={n.href}
                className={cn(
                  "flex h-7 items-center gap-1.5 rounded-md px-2.5 text-[12.5px] text-fg-muted transition-colors hover:bg-elevated hover:text-fg",
                  pathname.startsWith(n.href) && "bg-elevated text-fg",
                )}
              >
                <n.icon className="size-3.5" />
                {n.label}
              </Link>
            ))}
          </nav>
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="sm" className="gap-2">
              <span className="flex size-5 items-center justify-center rounded-full bg-accent/25 text-[10px] font-bold uppercase text-accent">
                {user?.display_name?.[0] ?? user?.email?.[0] ?? <UserIcon className="size-3" />}
              </span>
              <span className="max-w-[140px] truncate">{user?.display_name || user?.email || "…"}</span>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-52">
            <DropdownMenuLabel className="normal-case tracking-normal text-fg-muted">{user?.email}</DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem asChild>
              <Link href="/settings">
                <Settings /> Account settings
              </Link>
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => logout.mutate()} destructive>
              <LogOut /> Sign out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </header>
      <main className="flex-1">{children}</main>
    </div>
  );
}
