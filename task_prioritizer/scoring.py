"""Rank tasks by unblockability — spawn the highest score first.

Scoring (highest = spawn first):
    +100  pure code (type "code", no external dependency)
    +80   money lane
    +60   fixes a critical blocker
    +40   internal dependencies already satisfied
    +40   platform probe cache says GO
    +20   fast (expected <= 3 minutes)
    -100  needs an external service / network dependency
    -100  needs browser auth / OAuth / captcha
    -80   platform probe cache says BLOCKED
    -60   needs user action
    -40   has unsatisfied dependencies
    -20   slow (expected >= 10 minutes)
"""

import json
import sys
from pathlib import Path


def load_tasks(path=None):
    """Load a task list from a JSON file, or stdin when no path is given.

    Accepts either a bare JSON array or an object with a "tasks" key.
    """
    if path:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = json.load(sys.stdin)
    if isinstance(data, dict):
        return data.get("tasks", [])
    return data


def load_platform_cache(path=None):
    """Load an optional platform probe cache: {platform: {"verdict": "GO"|"BLOCKED"}}."""
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def score_task(task, cache=None):
    """Return (score, reasons) for one task dict."""
    cache = cache or {}
    score = 0
    reasons = []

    if task.get("external", False):
        score -= 100
        reasons.append("external_dep")

    platform = str(task.get("platform", "")).lower()
    if platform:
        verdict = cache.get(platform, {}).get("verdict")
        if verdict == "BLOCKED":
            score -= 80
            reasons.append(f"platform_blocked:{platform}")
        elif verdict == "GO":
            score += 40
            reasons.append(f"platform_ready:{platform}")

    if task.get("needs_auth", False):
        score -= 100
        reasons.append("needs_auth")

    if task.get("needs_user_action", False):
        score -= 60
        reasons.append("needs_user")

    if task.get("money_lane", False):
        score += 80
        reasons.append("money_lane")

    if task.get("critical", False):
        score += 60
        reasons.append("critical")

    if task.get("type") == "code" and not task.get("external"):
        score += 100
        reasons.append("pure_code")

    expected = task.get("expected_minutes")
    if isinstance(expected, (int, float)):
        if expected <= 3:
            score += 20
            reasons.append("fast")
        elif expected >= 10:
            score -= 20
            reasons.append("slow")

    deps = task.get("depends_on", []) or []
    unsatisfied = [d for d in deps if not Path(d).exists()]
    if unsatisfied:
        score -= 40
        reasons.append(f"unsatisfied_deps:{unsatisfied}")
    elif deps:
        score += 40
        reasons.append("deps_satisfied")

    return score, reasons


def rank_tasks(tasks, cache=None):
    """Return tasks sorted by rank score, highest first.

    Each task dict is copied and annotated with "rank_score" and
    "rank_reasons". Ties keep input order.
    """
    ranked = []
    for task in tasks:
        score, reasons = score_task(task, cache)
        ranked.append({**task, "rank_score": score, "rank_reasons": reasons})
    ranked.sort(key=lambda t: t["rank_score"], reverse=True)
    return ranked
