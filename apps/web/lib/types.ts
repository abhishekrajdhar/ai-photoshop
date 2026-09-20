/** API and timeline types mirrored from the backend Pydantic models. */

export interface User {
  id: string;
  email: string;
  display_name: string;
  settings: Record<string, unknown>;
  created_at: string;
}

export interface AuthResponse {
  user: User;
  access_token: string;
  expires_in: number;
}

export type TargetPlatform =
  | "youtube"
  | "instagram_reels"
  | "youtube_shorts"
  | "tiktok"
  | "podcast"
  | "linkedin"
  | "twitter"
  | "generic";

export interface ProjectSettings {
  target_platform: TargetPlatform;
  aspect_ratio: string;
  fps: number | null;
  filler_words: string[] | null;
  silence_threshold_db: number;
  silence_min_duration: number;
  caption_style: Record<string, unknown>;
}

export interface Project {
  id: string;
  name: string;
  description: string;
  status: "active" | "archived";
  settings: ProjectSettings;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  asset_count: number;
  thumbnail_url: string | null;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export type JobStatus = "QUEUED" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED";

export interface Job {
  id: string;
  project_id: string | null;
  type: string;
  status: JobStatus;
  progress: number;
  message: string;
  error: string | null;
  retry_count: number;
  max_retries: number;
  meta: Record<string, unknown>;
  result: Record<string, unknown>;
  queued_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface MediaMetadata {
  container: string | null;
  video_codec: string | null;
  audio_codec: string | null;
  width: number | null;
  height: number | null;
  fps: number | null;
  duration: number | null;
  bitrate: number | null;
  audio_channels: number | null;
  sample_rate: number | null;
  rotation: number;
}

export type AssetKind =
  | "original"
  | "proxy"
  | "audio"
  | "thumbnail"
  | "frame"
  | "render"
  | "export"
  | "caption"
  | "broll"
  | "music"
  | "image";

export interface MediaAsset {
  id: string;
  project_id: string;
  parent_asset_id: string | null;
  kind: AssetKind;
  media_type: "video" | "audio" | "image" | "text";
  filename: string;
  mime_type: string;
  size_bytes: number;
  content_hash: string | null;
  status: "pending" | "processing" | "ready" | "failed" | "duplicate";
  error: string | null;
  role: string | null;
  extra: Record<string, unknown>;
  metadata: MediaMetadata | null;
  proxy_asset_id: string | null;
  audio_asset_id: string | null;
  thumbnail_url: string | null;
  stream_url: string;
  waveform_url: string | null;
  created_at: string;
  updated_at: string;
}

/* ── Timeline document ───────────────────────────────────────────────────── */

export type TrackKind = "video" | "audio" | "caption" | "overlay";
export type ClipKind = "video" | "audio" | "image" | "caption" | "text" | "broll" | "music";
export type TransitionType = "cut" | "crossfade" | "fade_black" | "dip_to_white";

export interface Effect {
  id: string;
  type: string;
  start: number | null;
  duration: number | null;
  params: Record<string, unknown>;
  enabled: boolean;
}

export interface Transition {
  type: TransitionType;
  duration: number;
}

export interface WordTiming {
  text: string;
  start: number;
  end: number;
}

export interface Clip {
  id: string;
  kind: ClipKind;
  name: string;
  asset_id: string | null;
  timeline_start: number;
  duration: number;
  source_in: number;
  source_out: number;
  speed: number;
  gain_db: number;
  muted: boolean;
  text: string | null;
  words: WordTiming[] | null;
  style: Record<string, unknown>;
  position: { x: number; y: number; w: number; h: number } | null;
  effects: Effect[];
  transition_in: Transition;
  transition_out: Transition;
  linked_clip_id: string | null;
  loop: boolean;
  fade_in: number;
  fade_out: number;
  ducking: boolean;
  meta: Record<string, unknown>;
}

export interface Track {
  id: string;
  kind: TrackKind;
  name: string;
  index: number;
  muted: boolean;
  locked: boolean;
  hidden: boolean;
  clips: Clip[];
}

export interface Marker {
  id: string;
  time: number;
  label: string;
  color: string;
  kind: string;
  meta: Record<string, unknown>;
}

export interface CaptionStyle {
  font: string;
  font_size: number;
  color: string;
  highlight_color: string;
  background: string | null;
  outline: number;
  outline_color: string;
  shadow: number;
  position: "top" | "center" | "bottom";
  alignment: "left" | "center" | "right";
  margin_v: number;
  animation: "none" | "karaoke" | "pop" | "word";
  uppercase: boolean;
  max_words_per_cue: number;
  preset: string;
}

export interface TimelineSettings {
  width: number;
  height: number;
  fps: number;
  aspect_ratio: string;
  background: string;
  sample_rate: number;
  caption_style: CaptionStyle;
  audio: Record<string, unknown>;
  reframe: { mode: string; keyframes?: { t: number; x: number; y: number }[] } | null;
}

export interface TimelineDocument {
  schema_version: number;
  timeline_id: string;
  name: string;
  settings: TimelineSettings;
  tracks: Track[];
  markers: Marker[];
  meta: Record<string, unknown>;
}

export interface Timeline {
  id: string;
  project_id: string;
  name: string;
  kind: "main" | "short" | "alternate";
  is_primary: boolean;
  current_version_id: string | null;
  settings: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface TimelineVersion {
  id: string;
  timeline_id: string;
  version: number;
  parent_version_id: string | null;
  label: string;
  source: "user" | "ai" | "system";
  duration: number;
  created_at: string;
  operation_count: number;
}

export interface TimelineState {
  timeline: Timeline;
  version: TimelineVersion;
  document: TimelineDocument;
  can_undo: boolean;
  can_redo: boolean;
}

export interface EditOperation {
  id?: string;
  type: string;
  asset_id?: string | null;
  source_clip_id?: string | null;
  track_id?: string | null;
  time_ref?: "source" | "timeline";
  start?: number | null;
  end?: number | null;
  timestamp?: number | null;
  duration?: number | null;
  segments?: Record<string, unknown>[] | null;
  params?: Record<string, unknown>;
  text?: string | null;
  query?: string | null;
  scale?: number | null;
  confidence?: number;
  reason?: string;
  source?: "ai" | "user" | "system";
  reversible?: boolean;
}

export interface ApplyOperationsResponse {
  state: TimelineState;
  applied: EditOperation[];
  rejected: { operation: EditOperation; reason: string }[];
  duration_before: number;
  duration_after: number;
}

/* ── Transcript ──────────────────────────────────────────────────────────── */

export interface TranscriptWord {
  id: string;
  index: number;
  start: number;
  end: number;
  text: string;
  confidence: number | null;
  speaker_id: string | null;
  is_filler: boolean;
}

export interface TranscriptSegment {
  id: string;
  index: number;
  start: number;
  end: number;
  text: string;
  speaker_id: string | null;
  confidence: number | null;
  words: TranscriptWord[];
}

export interface Speaker {
  id: string;
  label: string;
  display_name: string;
  color: string | null;
}

export interface Transcript {
  id: string;
  asset_id: string;
  provider: string;
  model: string;
  language: string | null;
  text: string;
  confidence: number | null;
  segments: TranscriptSegment[];
  speakers: Speaker[];
  created_at: string;
}

/* ── Analysis ────────────────────────────────────────────────────────────── */

export interface Scene {
  id: string;
  asset_id: string;
  index: number;
  start: number;
  end: number;
  thumbnail_url: string | null;
  description: string | null;
  labels: Record<string, unknown>;
}

export interface SilenceSegment {
  start: number;
  end: number;
  duration: number;
}

export interface AnalysisResult {
  id: string;
  asset_id: string | null;
  kind: string;
  provider: string | null;
  model: string | null;
  data: Record<string, unknown>;
  created_at: string;
}

export interface Highlight {
  id: string;
  asset_id: string | null;
  start: number;
  end: number;
  title: string;
  reason: string;
  caption_suggestion: string;
  score: number;
  factors: Record<string, number>;
  category: string | null;
}

/* ── Chat ────────────────────────────────────────────────────────────────── */

export interface ChatProposal {
  status: "proposed" | "applied" | "rejected" | "previewing";
  summary: string;
  operations: EditOperation[];
  estimated_duration_delta: number | null;
  warnings: string[];
  applied_version_id?: string;
  timelines_created?: { id: string; name: string }[];
}

export interface ChatMessage {
  id: string;
  session_id: string;
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  proposal: ChatProposal | null;
  tool_calls: Record<string, unknown>[];
  job_id: string | null;
  created_at: string;
}

export interface ChatSession {
  id: string;
  project_id: string;
  title: string;
  created_at: string;
  messages: ChatMessage[];
}

/* ── Renders / exports ───────────────────────────────────────────────────── */

export interface ExportPreset {
  id: string;
  name: string;
  description: string;
  width: number;
  height: number;
  fps: number | null;
  video_bitrate: string;
  audio_bitrate: string;
  codec: string;
  aspect_ratio: string;
}

export interface RenderOut {
  id: string;
  project_id: string;
  timeline_version_id: string;
  job_id: string | null;
  kind: "preview" | "final";
  status: JobStatus;
  preset: string;
  settings: Record<string, unknown>;
  output_asset_id: string | null;
  duration: number | null;
  error: string | null;
  download_url: string | null;
  created_at: string;
}

export interface ExportOut {
  id: string;
  project_id: string;
  render_id: string | null;
  timeline_version_id: string | null;
  job_id: string | null;
  format: string;
  preset: string;
  filename: string;
  status: JobStatus;
  settings: Record<string, unknown>;
  output_asset_id: string | null;
  size_bytes: number | null;
  error: string | null;
  download_url: string | null;
  created_at: string;
}

export interface ServerEvent {
  event: string;
  data: Record<string, unknown> & { job_id?: string; project_id?: string; type?: string; status?: JobStatus; progress?: number; message?: string };
  ts: string;
}
