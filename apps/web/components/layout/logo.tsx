import Link from "next/link";
import { Scissors } from "lucide-react";
import { APP_NAME, cn } from "@/lib/utils";

export function Logo({ className, href = "/dashboard", compact = false }: { className?: string; href?: string; compact?: boolean }) {
  return (
    <Link href={href} className={cn("flex items-center gap-2 font-semibold tracking-tight text-fg", className)}>
      <span className="flex size-6 items-center justify-center rounded-md bg-accent text-white shadow-[0_0_20px_rgba(124,92,255,.45)]">
        <Scissors className="size-3.5" />
      </span>
      {!compact && <span className="text-[14px]">{APP_NAME}</span>}
    </Link>
  );
}
