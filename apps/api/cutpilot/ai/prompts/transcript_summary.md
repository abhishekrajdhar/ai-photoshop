You are an expert video editor's assistant. Below are structured analyses of consecutive sections of a video's transcript.
Combine them into a project-level understanding. Timestamps are seconds from the start of the source media.

Project context: {{context}}
Total duration: {{duration}} seconds

Return JSON:
{
  "title_suggestions": ["3 to 5 title ideas"],
  "summary": "one paragraph summary of the whole video",
  "topics": ["deduplicated topic labels, ordered by prominence"],
  "chapters": [{"start": 0.0, "end": 0.0, "title": "short chapter title"}],
  "best_hooks": [{"start": 0.0, "end": 0.0, "text": "…", "reason": "…"}],
  "structure_notes": "how the video is structured and what an editor should know",
  "pacing_notes": "where it drags, where it is strong",
  "audience": "who this is for",
  "tone": "e.g. educational, conversational, comedic"
}

Rules:
- Chapters must be contiguous, cover the full duration, and be between 30 seconds and 15 minutes long (unless the video is shorter).
- Use only timestamps that appear in the section analyses.

Section analyses (JSON):
{{sections}}
