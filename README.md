# agent-task-prioritizer

Rank an agent's task queue by ROI and unblockability, and track/auto-resolve
blockers. One CLI, standard library only — no dependencies.

## What it does

- **`rank`** — scores a JSON task list by unblockability. Pure code first;
  tasks that need auth, a user, or a dead platform go last or get skipped.
- **`roi`** — scores the same list by reward per hour, so the work worth
  the most gets done first.
- **`leaderboard`** — reward-per-hour by task type, from your own
  completed-work log, with a confidence level per type.
- **`blocker`** — log blockers with timestamps, list recent ones, and
  auto-resolve known patterns (dead processes, dead API keys, failed
  claims) with an escalation cap. Funding/approval blockers always skip —
  they need a human.

## Install

Python 3.9+, no dependencies.

```bash
git clone https://github.com/manteclaw/agent-task-prioritizer
cd agent-task-prioritizer
```

## Usage

### Rank by unblockability

```bash
$ python3 -m task_prioritizer rank --tasks examples/tasks.json
#     score  task
------------------------------------------------------------
1       160  Write API client for payments provider
             [money_lane, pure_code, slow]
2       140  Fix failing CI pipeline
             [critical, pure_code, slow]
3        80  Review security audit findings
             [critical, slow, deps_satisfied]
4       -20  Draft launch blog post
             [slow]
5       -20  Reply to support tickets
             [slow]
6      -120  Research competitor pricing
             [external_dep, slow]
7      -220  Set up analytics dashboard
             [external_dep, needs_auth, slow]
8      -220  Migrate database to new host
             [external_dep, needs_user, slow, unsatisfied_deps:['backups/db-snapshot.sql']]
```

Scoring: +100 pure code, +80 money lane, +60 critical, +40 deps satisfied,
+40 platform GO, +20 fast (≤3 min); −100 external, −100 needs auth,
−80 platform BLOCKED, −60 needs user, −40 unsatisfied deps, −20 slow
(≥10 min). Tasks can also come from stdin. Add `--json` for
machine-readable output.

### Rank by ROI

```bash
$ python3 -m task_prioritizer roi --tasks examples/tasks.json
#     score      $/hr    reward  task
------------------------------------------------------------
1      59.8     400.0     300.0  Write API client for payments provider
2      55.9     360.0     150.0  Fix failing CI pipeline
3      41.5     266.7     400.0  Review security audit findings
4      41.5     216.0     180.0  Set up analytics dashboard
5      26.8     120.0      80.0  Draft launch blog post
6      26.8     120.0     120.0  Research competitor pricing
7      12.3     125.0     250.0  Migrate database to new host
8       8.9      90.0      30.0  Reply to support tickets
```

Score is 0–100 and relative — compare tasks against each other, not
against an absolute bar. It combines reward per hour (up to 50 points),
a small penalty for long descriptions, and bonuses for code-type (+20)
and research/writing-type (+15) work.

### Leaderboard: which kind of work pays best

```bash
$ python3 -m task_prioritizer leaderboard --metrics examples/metrics.jsonl --unit USD
Task Type Profitability Leaderboard
============================================================
Rank   Type             USD/hr    Avg Rwd  Quality  Samples Conf
------------------------------------------------------------
1      review            314.3      275.0     0.93        2 low
2      code              225.6      117.5     0.84        4 med
3      writing           190.9       87.5     0.84        4 med
4      research           96.7       96.7     0.77        3 med

Best type: review @ 314.3 USD/hr (confidence: low)
```

Reads a metrics JSONL log of completed work — one object per line:

```json
{"task_type": "code", "reward": 120, "duration_s": 1800, "quality": 0.9}
```

Confidence is by sample count (`low` < 3, `med` < 10, `high` ≥ 10).
Trust a type only once it has enough samples — the example's top type
has just 2.

### Blockers

```bash
# Log one
python3 -m task_prioritizer blocker log example-api "api 401 on /v1/jobs" "rotate key" high

# List recent ones
python3 -m task_prioritizer blocker list --hours 24

# Dry-run auto-resolution (nothing executes, nothing is written)
python3 -m task_prioritizer blocker resolve --check --blockers examples/blockers.jsonl --resolvers examples/resolvers.json
# — blocker resolve: CHECK (dry-run) —
# ▸ example-api: api 401 on /v1/jobs
#   ↪ [CHECK] Would check EXAMPLE_API_KEY (present: False) and run health check: ...
# ▸ worker: process dead, no heartbeat for 10 minutes
#   ↪ [FAILED] No PID entry for worker (supply one with --pids)
# ▸ billing: funding needed to top up API balance
#   ↪ [SKIPPED] Funding/approval requires a human — skipping auto-resolution

# Actually attempt it
python3 -m task_prioritizer blocker resolve --resolve --blockers examples/blockers.jsonl --resolvers examples/resolvers.json
```

Auto-resolve is deliberately conservative:

- Funding/approval blockers are **skipped** — they need a human.
- Unknown patterns are **skipped** and reported, not acted on.
- The rest only run commands **you** configured in a resolvers file
  (`--resolvers`, or `TASKPRIORITIZER_RESOLVERS`): `restart` for a dead
  process, `health_check` for an auth failure, `verify_tx` for a failed
  claim (with `{tx}` as the hash placeholder). See
  `examples/resolvers.json`.
- A blocker that fails 3 times is **escalated** and never retried
  automatically. Every attempt is recorded in the resolutions log.

## Task input format

A JSON array (or an object with a `"tasks"` key). Every field is optional
except `name`; missing fields score neutral. See `examples/tasks.json`
and `SKILL.md` for the full field list.

## Configuration

All paths can come from flags, env vars, or defaults. See `.env.example`.

| Env var | Default |
|---|---|
| `TASKPRIORITIZER_BLOCKERS` | `~/.local/share/task-prioritizer/blockers.jsonl` |
| `TASKPRIORITIZER_RESOLUTIONS` | `~/.local/share/task-prioritizer/resolutions.jsonl` |
| `TASKPRIORITIZER_METRICS` | `~/.local/share/task-prioritizer/metrics.jsonl` |
| `TASKPRIORITIZER_CACHE` | (none — platform rules off) |
| `TASKPRIORITIZER_RESOLVERS` | (none — safe defaults) |

## Origin

Generalized from five small scripts that ranked a task queue by
unblockability, ROI, and type, and tracked blockers: hardcoded paths
and single-vendor inputs were replaced with CLI flags and env vars,
and the auto-resolver was rebuilt as a config-driven framework that
does nothing without your explicit commands. No secrets, no vendor
lock-in, no network calls — it only reads the files you point it at.

## License

MIT — see [LICENSE](LICENSE).
