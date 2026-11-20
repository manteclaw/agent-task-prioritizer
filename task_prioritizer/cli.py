"""Command line interface for agent-task-prioritizer.

Usage:
    python3 -m task_prioritizer rank [--tasks tasks.json] [--platform-cache cache.json]
    python3 -m task_prioritizer roi [--tasks tasks.json] [--top 10]
    python3 -m task_prioritizer leaderboard [--metrics metrics.jsonl]
    python3 -m task_prioritizer blocker log <service> <issue> <action> [severity]
    python3 -m task_prioritizer blocker list [--hours 24]
    python3 -m task_prioritizer blocker resolve [--check | --resolve]

All subcommands accept --json for machine-readable output.
Paths can also come from env vars; see blockers.py for the list.
"""

import argparse
import json
import sys

from . import __version__
from .blockers import (
    default_cache_path,
    default_metrics_path,
    default_resolvers_path,
    list_blockers,
    log_blocker,
    resolve_blockers,
)
from .leaderboard import analyze_metrics
from .roi import rank_by_roi
from .scoring import load_platform_cache, load_tasks, rank_tasks


def _print_json(obj):
    print(json.dumps(obj, indent=2))


def _cmd_rank(args):
    tasks = load_tasks(args.tasks)
    cache = load_platform_cache(args.platform_cache or default_cache_path())
    ranked = rank_tasks(tasks, cache)
    if args.top:
        ranked = ranked[: args.top]
    if args.json:
        _print_json(ranked)
        return 0
    if not ranked:
        print("No tasks found.")
        return 0
    print(f"{'#':<4} {'score':>6}  task")
    print("-" * 60)
    for i, task in enumerate(ranked, 1):
        reasons = ", ".join(task["rank_reasons"])
        print(f"{i:<4} {task['rank_score']:>6}  {task.get('name', 'unnamed')}")
        if reasons:
            print(f"{'':<4} {'':>6}  [{reasons}]")
    return 0


def _cmd_roi(args):
    tasks = load_tasks(args.tasks)
    ranked = rank_by_roi(tasks)
    if args.top:
        ranked = ranked[: args.top]
    if args.json:
        _print_json(ranked)
        return 0
    if not ranked:
        print("No tasks found.")
        return 0
    print(f"{'#':<4} {'score':>6}  {'$/hr':>8}  {'reward':>8}  task")
    print("-" * 60)
    for i, task in enumerate(ranked, 1):
        print(
            f"{i:<4} {task['roi_score']:>6}  {task['reward_per_hour']:>8.1f}  "
            f"{float(task.get('reward', 0) or 0):>8.1f}  {task.get('name', 'unnamed')}"
        )
    return 0


def _cmd_leaderboard(args):
    metrics = args.metrics or default_metrics_path()
    rows, error = analyze_metrics(metrics)
    if error:
        print(error)
        print("Log completed work first, e.g.:")
        print('  {"task_type": "code", "reward": 120, "duration_s": 1800, "quality": 0.9}')
        return 1
    if args.json:
        _print_json(rows)
        return 0
    if not rows:
        print(f"No metrics in {metrics} yet.")
        return 0
    unit = args.unit
    print("Task Type Profitability Leaderboard")
    print("=" * 60)
    print(
        f"{'Rank':<6} {'Type':<12} {unit + '/hr':>10} {'Avg Rwd':>10} "
        f"{'Quality':>8} {'Samples':>8} {'Conf':<5}"
    )
    print("-" * 60)
    for i, row in enumerate(rows, 1):
        print(
            f"{i:<6} {row['type']:<12} {row['reward_per_hour']:>10.1f} "
            f"{row['avg_reward']:>10.1f} {row['avg_quality']:>8.2f} "
            f"{row['samples']:>8} {row['confidence']:<5}"
        )
    if rows:
        best = rows[0]
        print(
            f"\nBest type: {best['type']} @ {best['reward_per_hour']:,.1f} "
            f"{unit}/hr (confidence: {best['confidence']})"
        )
    return 0


def _cmd_blocker_log(args):
    entry = log_blocker(args.service, args.issue, args.action, args.severity, args.blockers)
    if args.json:
        _print_json(entry)
    else:
        print(f"Blocker logged: {entry['service']} — {entry['issue'][:60]}")
    return 0


def _cmd_blocker_list(args):
    entries = list_blockers(args.hours, args.blockers)
    if args.json:
        _print_json(entries)
        return 0
    if not entries:
        print("No blockers logged yet")
        return 0
    print(f"\nBLOCKERS LAST {args.hours}H")
    print("=" * 60)
    for entry in entries:
        print(
            f"  {entry['timestamp'][:19]} | {entry['service'][:15]:15s} | "
            f"{entry['severity'][:6]:6s} | {entry['issue'][:40]}"
        )
    print(f"\nTotal: {len(entries)} blockers")
    return 0


def _cmd_blocker_resolve(args):
    if not args.check and not args.resolve:
        print("Usage: blocker resolve --check | --resolve")
        return 1
    results = resolve_blockers(
        blockers_path=args.blockers,
        resolutions_path=args.resolutions,
        resolvers_path=args.resolvers or default_resolvers_path(),
        pids_path=args.pids,
        check_only=args.check,
    )
    if not results:
        print("No blockers found")
        return 0
    mode = "CHECK (dry-run)" if args.check else "RESOLVE"
    print(f"— blocker resolve: {mode} —")
    counts = {"resolved": 0, "failed": 0, "skipped": 0, "escalated": 0, "check": 0}
    for result in results:
        status = result["status"]
        counts[status] = counts.get(status, 0) + 1
        print(f"▸ {result['service']}: {result['issue'][:80]}")
        print(f"  ↪ [{status.upper()}] {result['details'][:200]}")
    print("— Summary —")
    print(f"  Resolved:  {counts['resolved']}")
    print(f"  Failed:    {counts['failed']}")
    print(f"  Skipped:   {counts['skipped']}")
    print(f"  Escalated: {counts['escalated']}")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="task-prioritizer",
        description="Rank an agent's task queue by ROI and unblockability, "
        "and track/auto-resolve blockers.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_rank = sub.add_parser("rank", help="Rank tasks by unblockability (highest first)")
    p_rank.add_argument("--tasks", help="JSON file with a task array (default: stdin)")
    p_rank.add_argument("--platform-cache", help="JSON platform probe cache")
    p_rank.add_argument("--top", type=int, help="Show only the top N tasks")
    p_rank.add_argument("--json", action="store_true", help="Machine-readable output")
    p_rank.set_defaults(func=_cmd_rank)

    p_roi = sub.add_parser("roi", help="Rank tasks by reward per hour (highest first)")
    p_roi.add_argument("--tasks", help="JSON file with a task array (default: stdin)")
    p_roi.add_argument("--top", type=int, help="Show only the top N tasks")
    p_roi.add_argument("--json", action="store_true", help="Machine-readable output")
    p_roi.set_defaults(func=_cmd_roi)

    p_lb = sub.add_parser(
        "leaderboard", help="Reward-per-hour leaderboard by task type from a metrics log"
    )
    p_lb.add_argument("--metrics", help="Metrics JSONL file")
    p_lb.add_argument("--unit", default="credits", help="Reward unit label (default: credits)")
    p_lb.add_argument("--json", action="store_true", help="Machine-readable output")
    p_lb.set_defaults(func=_cmd_leaderboard)

    p_blocker = sub.add_parser("blocker", help="Log, list, or auto-resolve blockers")
    b_sub = p_blocker.add_subparsers(dest="blocker_command", required=True)

    p_log = b_sub.add_parser("log", help="Log a blocker")
    p_log.add_argument("service", help="Service or platform where it happened")
    p_log.add_argument("issue", help="What went wrong")
    p_log.add_argument("action", help="What to try / what was tried")
    p_log.add_argument("severity", nargs="?", default="medium", help="low|medium|high")
    p_log.add_argument("--blockers", help="Blockers JSONL file")
    p_log.add_argument("--json", action="store_true")
    p_log.set_defaults(func=_cmd_blocker_log)

    p_list = b_sub.add_parser("list", help="List recent blockers")
    p_list.add_argument("--hours", type=int, default=24, help="Look-back window (default: 24)")
    p_list.add_argument("--blockers", help="Blockers JSONL file")
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=_cmd_blocker_list)

    p_resolve = b_sub.add_parser("resolve", help="Auto-resolve known blockers")
    p_resolve.add_argument("--check", action="store_true", help="Dry-run: list what it would do")
    p_resolve.add_argument("--resolve", action="store_true", help="Attempt resolution")
    p_resolve.add_argument("--blockers", help="Blockers JSONL file")
    p_resolve.add_argument("--resolutions", help="Resolutions JSONL file (attempt log)")
    p_resolve.add_argument("--resolvers", help="Resolvers config JSON (see examples/resolvers.json)")
    p_resolve.add_argument("--pids", help="JSON file mapping service names to PIDs")
    p_resolve.set_defaults(func=_cmd_blocker_resolve)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
