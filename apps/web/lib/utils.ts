import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

export function formatTime(seconds: number, opts: { frames?: boolean; fps?: number } = {}): string {
  if (!Number.isFinite(seconds) || seconds < 0) seconds = 0;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  const frac = seconds - Math.floor(seconds);
  const mm = String(m).padStart(2, "0");
  const ss = String(s).padStart(2, "0");
  if (opts.frames) {
    const fps = opts.fps ?? 30;
    const ff = String(Math.floor(frac * fps)).padStart(2, "0");
    return h > 0 ? `${h}:${mm}:${ss}:${ff}` : `${mm}:${ss}:${ff}`;
  }
  const ms = String(Math.floor(frac * 10));
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}.${ms}`;
}

export function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds)) return "–";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  if (m === 0) return `${s}s`;
  return `${m}m ${String(s).padStart(2, "0")}s`;
}

export function formatBytes(bytes: number): string {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

export function clamp(v: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, v));
}

export function relativeTime(iso: string): string {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)}d ago`;
  return new Date(iso).toLocaleDateString();
}

export const APP_NAME = process.env.NEXT_PUBLIC_APP_NAME ?? "CutPilot AI";
