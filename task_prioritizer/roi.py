"""Rank tasks by expected return on effort (ROI).

Score is 0-100 and RELATIVE — compare tasks against each other, not
against an absolute bar. "reward" is in whatever unit you track
(dollars, credits, points); effort is in minutes.

    up to +50  reward rate (reward per hour, scaled)
    -2 per 1000 chars of description (long descriptions = fiddly work)
    +20         code-type work (build / implement / script / fix ...)
    +15         research / writing work

A task needs "reward" and "effort_minutes" (or "expected_minutes")
to score well; tasks without a reward score near zero.
"""

CODE_KEYWORDS = ("code", "python", "script", "build", "implement", "fix", "refactor")
RESEARCH_KEYWORDS = ("writeup", "analysis", "compare", "research", "review", "draft")


def roi_score(task):
    """Return (score 0-100, reward_per_hour) for one task dict."""
    reward = float(task.get("reward", 0) or 0)
    effort = float(
        task.get("effort_minutes", task.get("expected_minutes", 60)) or 60
    )
    if effort <= 0:
        effort = 60.0
    description = str(task.get("description", ""))
    text = f"{task.get('name', '')} {description}".lower()

    reward_per_hour = reward * 60.0 / effort
    score = min(reward_per_hour / 10.0, 50.0)

    # Complexity penalty: long descriptions usually mean fiddly work.
    score -= len(description) / 1000.0 * 2.0

    if any(k in text for k in CODE_KEYWORDS):
        score += 20
    if any(k in text for k in RESEARCH_KEYWORDS):
        score += 15

    return max(0.0, min(100.0, score)), reward_per_hour


def rank_by_roi(tasks):
    """Return tasks sorted by ROI score, highest first.

    Each task dict is copied and annotated with "roi_score" and
    "reward_per_hour".
    """
    ranked = []
    for task in tasks:
        score, rate = roi_score(task)
        ranked.append({**task, "roi_score": round(score, 1), "reward_per_hour": round(rate, 1)})
    ranked.sort(key=lambda t: t["roi_score"], reverse=True)
    return ranked
