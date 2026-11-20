---
name: agent-task-prioritizer
description: Rank an agent's task queue by ROI and unblockability, and track/auto-resolve blockers. Use when deciding what to work on next, which task to spawn first, or which kind of work pays best. Input is a JSON task list; output is a ranked list with reasons.
license: MIT
compatibility: Python 3.9+, standard library only, any OS
metadata:
  author: manteclaw
  version: "1.0.0"
  tags: tasks prioritization roi productivity agents automation
---

## Agent Task Prioritizer

Rank a queue of tasks before you start them, so the work that is unblocked
and worth the most gets done first — and the work that needs auth, a user,
or a dead platform goes last or gets skipped.

### When to use

- You have a list of pending tasks and need to pick the next one.
- You are about to spawn subagents and want the spawn order decided by
  unblockability, not by gut feel.
- You want to know which type of work (code, research, writing, review…)
  earns the most per hour from your own history.
- A task hit a dead end and you want the blocker logged, then
  auto-resolved later if a known fix exists.

### How to use

No dependencies — Python 3.9+ standard library only.

```bash
git clone https://github.com/manteclaw/agent-task-prioritizer
cd agent-task-prioritizer

# Rank by unblockability: pure code first, auth/user/dead-platform last
python3 -m task_prioritizer rank --tasks examples/tasks.json

# Rank by return on effort (reward per hour)
python3 -m task_prioritizer roi --tasks examples/tasks.json

# Which kind of work pays best, from your own completed-work log
python3 -m task_prioritizer leaderboard --metrics examples/metrics.jsonl

# Log a blocker, list recent ones, dry-run auto-resolution
python3 -m task_prioritizer blocker log example-api "api 401 on /v1/jobs" "rotate key" high
python3 -m task_prioritizer blocker list --hours 24
python3 -m task_prioritizer blocker resolve --check --blockers examples/blockers.jsonl --resolvers examples/resolvers.json
```

Add `--json` to any command for machine-readable output.

### Task input format

A JSON array (or an object with a `"tasks"` key). Every field is optional
except `name`; missing fields just score neutral.

```json
[
  {
    "name": "Write API client for payments provider",
    "type": "code",
    "description": "Build a small client library for the payments API.",
    "external": false,
    "needs_auth": false,
    "needs_user_action": false,
    "money_lane": true,
    "critical": false,
    "expected_minutes": 45,
    "effort_minutes": 45,
    "reward": 300,
    "reward_unit": "USD",
    "platform": "payments-provider",
    "depends_on": ["src/payments.py"]
  }
]
```

Field meanings:

| Field | Meaning |
|---|---|
| `name` | Task title |
| `type` | `code`, `research`, `writing`, `review`, `ops`, or anything else |
| `description` | Free text; used for the ROI complexity penalty and keyword bonuses |
| `external` | Needs an external service / network dependency |
| `needs_auth` | Needs browser auth, OAuth, or a captcha |
| `needs_user_action` | Blocked until a human does something |
| `money_lane` | Directly earns money |
| `critical` | Fixes a critical blocker |
| `expected_minutes` | How long it should take (drives fast/slow scoring) |
| `effort_minutes` | How long it should take (drives ROI; falls back to `expected_minutes`) |
| `reward` | Payout in whatever unit you track (dollars, credits, points) |
| `reward_unit` | Label for the reward unit, e.g. `USD` |
| `platform` | Platform the task touches; scored against a probe cache if you supply one |
| `depends_on` | File paths that must exist for the task to be unblocked |

### Ranking rules (`rank`)

Highest score = do first. Lowest = do last or skip.

| Points | Rule |
|---|---|
| +100 | Pure code (`type` is `code`, no external dependency) |
| +80 | Money lane |
| +60 | Fixes a critical blocker |
| +40 | Dependencies already satisfied (all `depends_on` paths exist) |
| +40 | Platform probe cache says GO |
| +20 | Fast (expected ≤ 3 minutes) |
| −100 | External dependency |
| −100 | Needs auth |
| −80 | Platform probe cache says BLOCKED |
| −60 | Needs user action |
| −40 | Has unsatisfied dependencies |
| −20 | Slow (expected ≥ 10 minutes) |

Pass `--platform-cache cache.json` with a `{"platform": {"verdict": "GO"|"BLOCKED"}}`
map to apply the platform rules, or set `TASKPRIORITIZER_CACHE`.

### ROI rules (`roi`)

Score is 0–100 and **relative** — compare tasks against each other, not
against an absolute bar. It combines reward per hour (up to 50 points),
a small penalty for long descriptions (fiddly work), and bonuses for
code-type (+20) and research/writing-type (+15) work.

### Leaderboard rules (`leaderboard`)

Reads a metrics JSONL log of completed work — one object per line:

```json
{"task_type": "code", "reward": 120, "duration_s": 1800, "quality": 0.9}
```

Outputs reward per hour by type, with average reward, average quality,
sample count, and confidence (`low` < 3 samples, `med` < 10, `high` ≥ 10).
Trust a type only once it has enough samples.

### Blockers (`blocker`)

- `blocker log <service> <issue> <action> [severity]` — append one line to
  the blockers log (default `~/.local/share/task-prioritizer/blockers.jsonl`,
  or `TASKPRIORITIZER_BLOCKERS`, or `--blockers`).
- `blocker list [--hours 24]` — recent blockers.
- `blocker resolve --check | --resolve` — try a handler for each known
  pattern. `--check` is a dry run: nothing executes, nothing is written.

Auto-resolve is deliberately conservative:

- Anything about funding or approval is **skipped** — it needs a human.
- Anything with no matching handler is **skipped** and reported.
- The remaining handlers only run commands **you** configured in a
  resolvers file (`--resolvers`, or `TASKPRIORITIZER_RESOLVERS`):
  `restart` for a dead process, `health_check` for an auth failure,
  `verify_tx` for a failed claim (with `{tx}` as the hash placeholder).
  See `examples/resolvers.json`.
- A blocker that fails 3 times is **escalated** and never retried
  automatically. Every attempt is recorded in the resolutions log
  (`TASKPRIORITIZER_RESOLUTIONS`).

### Configuration

All paths can come from flags, env vars, or defaults. See `.env.example`.

| Env var | Default |
|---|---|
| `TASKPRIORITIZER_BLOCKERS` | `~/.local/share/task-prioritizer/blockers.jsonl` |
| `TASKPRIORITIZER_RESOLUTIONS` | `~/.local/share/task-prioritizer/resolutions.jsonl` |
| `TASKPRIORITIZER_METRICS` | `~/.local/share/task-prioritizer/metrics.jsonl` |
| `TASKPRIORITIZER_CACHE` | (none — platform rules off) |
| `TASKPRIORITIZER_RESOLVERS` | (none — safe defaults) |

### Reply integrity

Present ONLY scores the tool computed from the input you gave it. Do not
invent rewards, durations, or platform verdicts. If the input has no
reward data, say the ROI ranking is meaningless for it — do not guess.
