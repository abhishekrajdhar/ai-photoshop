"""faster-whisper as a child process: `python -m cutpilot.ai.whisper_cli --audio a.wav --out r.json`.

Keeps the model's memory out of the long-lived worker (see Settings.whisper_subprocess). Progress is
reported on stdout as `progress <fraction>` lines; the transcript is written as JSON to --out.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="base")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--compute", default="int8")
    ap.add_argument("--threads", type=int, default=0)
    ap.add_argument("--language", default=None)
    ap.add_argument("--duration", type=float, default=0.0)
    a = ap.parse_args(argv)

    from faster_whisper import WhisperModel

    kw = {"cpu_threads": a.threads, "num_workers": 1} if a.threads > 0 else {}
    model = WhisperModel(a.model, device=a.device, compute_type=a.compute, **kw)
    seg_iter, info = model.transcribe(
        a.audio, language=a.language, word_timestamps=True, vad_filter=True
    )
    segments = []
    for seg in seg_iter:
        segments.append(
            {
                "start": round(seg.start, 3),
                "end": round(seg.end, 3),
                "text": seg.text.strip(),
                "confidence": round(math.exp(seg.avg_logprob), 4) if seg.avg_logprob else None,
                "words": [
                    {
                        "start": round(w.start, 3),
                        "end": round(w.end, 3),
                        "text": w.word.strip(),
                        "confidence": round(float(w.probability), 4),
                    }
                    for w in (seg.words or [])
                ],
            }
        )
        if a.duration > 0:
            print(f"progress {min(0.99, seg.end / a.duration):.3f}", flush=True)
    Path(a.out).write_text(
        json.dumps({"language": info.language, "segments": segments}), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
