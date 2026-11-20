"""Reward-per-hour leaderboard by task type, from a metrics JSONL log.

Each line of the log is one completed task:
    {"task_type": "code", "reward": 120, "duration_s": 1800, "quality": 0.9}

"reward" is in whatever unit you track; "quality" is 0-1 and optional.
Confidence is by sample count: low < 3, med < 10, high >= 10.
"""

import json
from collections import defaultdict
from pathlib import Path

MIN_SAMPLES = 3


def analyze_metrics(path):
    """Return (rows, error). Rows are sorted by reward/hour, highest first.

    Each row: type, reward_per_hour, avg_reward, avg_quality, samples,
    confidence ("low" | "med" | "high").
    """
    p = Path(path)
    if not p.exists():
        return [], f"No metrics file found at {path}"

    stats = defaultdict(
        lambda: {"count": 0, "total_reward": 0.0, "total_duration": 0.0, "total_quality": 0.0}
    )
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            tt = str(rec.get("task_type", "UNKNOWN"))
            s = stats[tt]
            s["count"] += 1
            s["total_reward"] += float(rec.get("reward", 0) or 0)
            s["total_duration"] += float(rec.get("duration_s", 0) or 0)
            s["total_quality"] += float(rec.get("quality", 0) or 0)

    rows = []
    for tt, s in stats.items():
        hours = s["total_duration"] / 3600.0 if s["total_duration"] > 0 else 0.001
        count = s["count"]
        rows.append(
            {
                "type": tt,
                "reward_per_hour": round(s["total_reward"] / hours, 1),
                "avg_reward": round(s["total_reward"] / count, 1) if count else 0,
                "avg_quality": round(s["total_quality"] / count, 2) if count else 0,
                "samples": count,
                "confidence": "low" if count < MIN_SAMPLES else "med" if count < 10 else "high",
            }
        )
    rows.sort(key=lambda r: r["reward_per_hour"], reverse=True)
    return rows, None
