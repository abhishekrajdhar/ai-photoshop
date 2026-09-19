import { Logo } from "@/components/layout/logo";

export function AuthCard({ title, subtitle, children, footer }: { title: string; subtitle?: string; children: React.ReactNode; footer?: React.ReactNode }) {
  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden px-4">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top,rgba(124,92,255,.18),transparent_55%)]" />
      <div className="relative w-full max-w-sm">
        <div className="mb-6 flex justify-center">
          <Logo href="/" />
        </div>
        <div className="rounded-lg border border-border bg-panel p-6 shadow-2xl">
          <h1 className="text-[17px] font-semibold tracking-tight">{title}</h1>
          {subtitle && <p className="mt-1 text-[12.5px] text-fg-muted">{subtitle}</p>}
          <div className="mt-5">{children}</div>
        </div>
        {footer && <div className="mt-4 text-center text-[12.5px] text-fg-muted">{footer}</div>}
      </div>
    </div>
  );
}
