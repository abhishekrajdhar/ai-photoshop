import type { TargetPlatform } from "@/lib/types";

export const PLATFORMS: { id: TargetPlatform; label: string; aspect: string; hint: string }[] = [
  { id: "youtube", label: "YouTube", aspect: "16:9", hint: "Long-form, chapters, retention pacing" },
  { id: "youtube_shorts", label: "YouTube Shorts", aspect: "9:16", hint: "≤ 60 s vertical" },
  { id: "instagram_reels", label: "Instagram Reels", aspect: "9:16", hint: "Hook-first, captions on" },
  { id: "tiktok", label: "TikTok", aspect: "9:16", hint: "Fast cuts, bold captions" },
  { id: "linkedin", label: "LinkedIn", aspect: "1:1", hint: "Square, professional tone" },
  { id: "twitter", label: "X / Twitter", aspect: "16:9", hint: "Short, punchy" },
  { id: "podcast", label: "Podcast", aspect: "16:9", hint: "Multi-speaker, clean audio" },
  { id: "generic", label: "Generic", aspect: "16:9", hint: "No platform assumptions" },
];

export const PLATFORM_LABEL: Record<string, string> = Object.fromEntries(PLATFORMS.map((p) => [p.id, p.label]));
