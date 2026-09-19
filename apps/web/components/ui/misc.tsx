"use client";
import * as React from "react";
import * as ProgressPrimitive from "@radix-ui/react-progress";
import * as SeparatorPrimitive from "@radix-ui/react-separator";
import * as PopoverPrimitive from "@radix-ui/react-popover";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

/* Badge */
const badgeVariants = cva(
  "inline-flex items-center rounded-sm border px-1.5 py-0.5 text-[10.5px] font-semibold uppercase tracking-wide",
  {
    variants: {
      variant: {
        default: "border-transparent bg-accent/20 text-accent",
        secondary: "border-border bg-elevated text-fg-muted",
        success: "border-transparent bg-success/15 text-success",
        warning: "border-transparent bg-warning/15 text-warning",
        danger: "border-transparent bg-danger/15 text-danger",
        info: "border-transparent bg-info/15 text-info",
        outline: "border-border text-fg-muted",
      },
    },
    defaultVariants: { variant: "default" },
  },
);
export function Badge({ className, variant, ...props }: React.HTMLAttributes<HTMLDivElement> & VariantProps<typeof badgeVariants>) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}

/* Progress */
export const Progress = React.forwardRef<
  React.ElementRef<typeof ProgressPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof ProgressPrimitive.Root> & { indeterminate?: boolean }
>(({ className, value, indeterminate, ...props }, ref) => (
  <ProgressPrimitive.Root ref={ref} className={cn("relative h-1.5 w-full overflow-hidden rounded-full bg-border-strong/60", className)} {...props}>
    <ProgressPrimitive.Indicator
      className={cn("h-full w-full flex-1 bg-accent transition-transform duration-300", indeterminate && "animate-pulse")}
      style={{ transform: `translateX(-${100 - (value ?? 0)}%)` }}
    />
  </ProgressPrimitive.Root>
));
Progress.displayName = "Progress";

/* Separator */
export const Separator = React.forwardRef<
  React.ElementRef<typeof SeparatorPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof SeparatorPrimitive.Root>
>(({ className, orientation = "horizontal", decorative = true, ...props }, ref) => (
  <SeparatorPrimitive.Root
    ref={ref}
    decorative={decorative}
    orientation={orientation}
    className={cn("shrink-0 bg-border", orientation === "horizontal" ? "h-px w-full" : "h-full w-px", className)}
    {...props}
  />
));
Separator.displayName = "Separator";

/* Skeleton */
export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("skeleton rounded-md", className)} {...props} />;
}

/* Popover */
export const Popover = PopoverPrimitive.Root;
export const PopoverTrigger = PopoverPrimitive.Trigger;
export const PopoverContent = React.forwardRef<
  React.ElementRef<typeof PopoverPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof PopoverPrimitive.Content>
>(({ className, align = "center", sideOffset = 4, ...props }, ref) => (
  <PopoverPrimitive.Portal>
    <PopoverPrimitive.Content
      ref={ref}
      align={align}
      sideOffset={sideOffset}
      className={cn("z-50 w-72 rounded-md border border-border bg-elevated p-3 text-fg shadow-xl outline-none", className)}
      {...props}
    />
  </PopoverPrimitive.Portal>
));
PopoverContent.displayName = "PopoverContent";

/* Kbd */
export function Kbd({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <kbd className={cn("inline-flex h-4.5 min-w-4.5 items-center justify-center rounded-sm border border-border bg-panel-2 px-1 text-mono text-[10px] text-fg-muted", className)}>
      {children}
    </kbd>
  );
}

/* Empty state */
export function EmptyState({ icon, title, description, action, className }: { icon?: React.ReactNode; title: string; description?: string; action?: React.ReactNode; className?: string }) {
  return (
    <div className={cn("flex flex-col items-center justify-center gap-2 p-8 text-center", className)}>
      {icon && <div className="mb-1 text-fg-subtle [&_svg]:size-8">{icon}</div>}
      <div className="text-[13px] font-medium text-fg">{title}</div>
      {description && <div className="max-w-xs text-[12px] text-fg-muted">{description}</div>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}
