"""Blocker log + auto-resolve framework.

A blocker is one JSON line:
    {"timestamp": "...", "service": "example-api",
     "issue": "api 401 on /v1/jobs", "action": "rotate key", "severity": "high"}

`blocker log` appends one. `blocker list` shows recent ones.
`blocker resolve` walks the log and tries a handler for each known
pattern, recording every attempt in a resolutions log. A blocker that
fails 3 times is escalated and never retried automatically.

Handlers are deliberately conservative:
  - anything about funding / approval is SKIPPED (needs a human);
  - anything unknown is SKIPPED (reported, not acted on);
  - the rest only run commands you configured in a resolvers file
    (see examples/resolvers.json) — nothing executes by surprise.

Paths come from flags, then env vars, then defaults under
~/.local/share/task-prioritizer/:
  TASKPRIORITIZER_BLOCKERS, TASKPRIORITIZER_RESOLUTIONS,
  TASKPRIORITIZER_METRICS, TASKPRIORITIZER_CACHE, TASKPRIORITIZER_RESOLVERS
"""

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DIR = Path.home() / ".local" / "share" / "task-prioritizer"
MAX_ATTEMPTS = 3

TX_RE = re.compile(r"0x[a-fA-F0-9]{64}")


def default_blockers_path():
    return Path(os.environ.get("TASKPRIORITIZER_BLOCKERS", DEFAULT_DIR / "blockers.jsonl"))


def default_resolutions_path():
    return Path(
        os.environ.get("TASKPRIORITIZER_RESOLUTIONS", DEFAULT_DIR / "resolutions.jsonl")
    )


def default_metrics_path():
    return Path(os.environ.get("TASKPRIORITIZER_METRICS", DEFAULT_DIR / "metrics.jsonl"))


def default_cache_path():
    value = os.environ.get("TASKPRIORITIZER_CACHE")
    return Path(value) if value else None


def default_resolvers_path():
    value = os.environ.get("TASKPRIORITIZER_RESOLVERS")
    return Path(value) if value else None


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def _read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    entries = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def _append_jsonl(path, entry):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _norm_blocker(raw):
    """Accept both "service"/"platform" and "issue"/"reason" spellings."""
    return {
        "service": raw.get("service", raw.get("platform", "unknown")),
        "issue": raw.get("issue", raw.get("reason", "unknown")),
        "action": raw.get("action", raw.get("action_taken", "")),
        "severity": raw.get("severity", "medium"),
        "timestamp": raw.get("timestamp", ""),
    }


# ── Logging / listing ──────────────────────────────────────────────

def log_blocker(service, issue, action, severity="medium", path=None):
    path = Path(path) if path else default_blockers_path()
    entry = {
        "timestamp": now_iso(),
        "service": service,
        "issue": issue,
        "action": action,
        "severity": severity,
    }
    _append_jsonl(path, entry)
    return entry


def list_blockers(hours=24, path=None):
    path = Path(path) if path else default_blockers_path()
    cutoff = datetime.now(timezone.utc).timestamp() - hours * 3600
    recent = []
    for raw in _read_jsonl(path):
        entry = _norm_blocker(raw)
        try:
            ts = datetime.fromisoformat(entry["timestamp"])
        except ValueError:
            continue
        if ts.timestamp() > cutoff:
            recent.append(entry)
    return recent


# ── Handlers ───────────────────────────────────────────────────────
# Each handler takes (blocker, service_config, check_only, context)
# and returns (status, details). Status is one of
# "resolved" | "failed" | "skipped" | "check" (dry-run).

def _run(cmd, timeout=30):
    try:
        proc = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return proc.returncode, (proc.stdout + proc.stderr).strip()
    except subprocess.TimeoutExpired:
        return 1, "command timed out"
    except Exception as exc:  # noqa: BLE001 - report, don't crash
        return 1, str(exc)


def _handler_funding(blocker, cfg, check_only, ctx):
    return "skipped", "Funding/approval requires a human — skipping auto-resolution"


def _handler_process_dead(blocker, cfg, check_only, ctx):
    service = blocker["service"]
    pids = ctx.get("pids", {})
    pid = pids.get(service)
    if pid is None:
        for key, val in pids.items():
            if service.lower() in key.lower() or key.lower() in service.lower():
                pid = val
                break
    if pid is None:
        return "failed", f"No PID entry for {service} (supply one with --pids)"
    alive = False
    try:
        alive = Path(f"/proc/{int(pid)}").exists()
    except (TypeError, ValueError):
        alive = False
    if alive:
        return "skipped", f"Process {pid} for {service} is still alive"
    restart = cfg.get("restart")
    if not restart:
        return "failed", (
            f"Process {pid} for {service} is dead and no restart command "
            "is configured for it in your resolvers file"
        )
    if check_only:
        return "check", f"Would run restart command for {service}: {restart}"
    rc, out = _run(restart, timeout=30)
    return ("resolved" if rc == 0 else "failed"), out[:500] or f"restart exited {rc}"


def _handler_api_auth(blocker, cfg, check_only, ctx):
    service = blocker["service"]
    env_name = cfg.get("api_key_env") or (
        service.upper().replace("-", "_").replace(" ", "_") + "_API_KEY"
    )
    key_present = bool(os.environ.get(env_name))
    health = cfg.get("health_check")
    if check_only:
        details = f"Would check {env_name} (present: {key_present})"
        if health:
            details += f" and run health check: {health}"
        return "check", details
    if health:
        rc, out = _run(health, timeout=60)
        if rc == 0 and "200" in out:
            return "resolved", f"Health check for {service} returned 200"
        return "failed", (
            f"Health check for {service} failed (rc={rc}). "
            f"Key {env_name} present: {key_present}. "
            "Rotate the key if it is dead."
        )
    if key_present:
        return "failed", (
            f"Key {env_name} is set but no health check is configured — "
            "verify the key manually"
        )
    return "failed", (
        f"No key found in {env_name} — set it, or add a health_check "
        "to your resolvers file"
    )


def _handler_claim(blocker, cfg, check_only, ctx):
    text = f"{blocker.get('issue', '')} {blocker.get('action', '')}"
    match = TX_RE.search(text)
    if not match:
        return "failed", "No transaction hash found in blocker text — cannot verify"
    tx = match.group(0)
    verify = cfg.get("verify_tx")
    if not verify:
        return "failed", f"Tx {tx[:20]}... found but no verify_tx command is configured"
    cmd = verify.replace("{tx}", tx)
    if check_only:
        return "check", f"Would verify tx on-chain: {cmd}"
    rc, out = _run(cmd, timeout=30)
    return ("resolved" if rc == 0 else "failed"), out[:500] or f"verify exited {rc}"


HANDLERS = [
    (("funding needed", "needs funding", "needs approval", "approval needed"), _handler_funding),
    (("process dead", "process not running", "service down", "worker died"), _handler_process_dead),
    (("api 401", "api 403", "unauthorized", "revoked", "auth failed"), _handler_api_auth),
    (("claim failed", "claim tx", "transaction"), _handler_claim),
]


def pick_handler(blocker):
    combined = f"{blocker.get('issue', '')} {blocker.get('action', '')}".lower()
    for keywords, handler in HANDLERS:
        if any(k in combined for k in keywords):
            return handler
    return None


# ── Resolve ────────────────────────────────────────────────────────

def _service_cfg(resolvers, service):
    services = (resolvers or {}).get("services", {})
    return services.get(service) or services.get(service.lower()) or {}


def resolve_blockers(blockers_path=None, resolutions_path=None, resolvers_path=None,
                     pids_path=None, check_only=True):
    """Walk the blocker log and attempt resolution. Returns a result list.

    In check mode nothing is executed and nothing is written.
    In resolve mode every attempt (and every escalation) is appended
    to the resolutions log.
    """
    blockers_path = Path(blockers_path) if blockers_path else default_blockers_path()
    resolutions_path = (
        Path(resolutions_path) if resolutions_path else default_resolutions_path()
    )
    resolvers = {}
    if resolvers_path and Path(resolvers_path).exists():
        with open(resolvers_path, encoding="utf-8") as f:
            resolvers = json.load(f)
    pids = {}
    if pids_path and Path(pids_path).exists():
        with open(pids_path, encoding="utf-8") as f:
            pids = json.load(f)

    blockers = [_norm_blocker(raw) for raw in _read_jsonl(blockers_path)]
    resolutions = _read_jsonl(resolutions_path)
    ctx = {"pids": pids}
    results = []

    for blocker in blockers:
        service, issue = blocker["service"], blocker["issue"]
        base = {"service": service, "issue": issue}

        attempts = sum(
            1 for r in resolutions
            if r.get("service") == service and r.get("issue") == issue
        )
        already_done = any(
            r.get("service") == service and r.get("issue") == issue
            and r.get("status") in ("resolved", "escalated")
            for r in resolutions
        )
        if already_done:
            results.append({**base, "status": "skipped",
                            "details": "Already resolved/escalated — skipping"})
            continue

        if attempts >= MAX_ATTEMPTS:
            entry = {
                "time": now_iso(), "service": service, "issue": issue,
                "handler": "escalation", "status": "escalated",
                "details": f"Auto-escalated after {attempts} failed attempts",
                "attempt": attempts + 1,
            }
            if not check_only:
                _append_jsonl(resolutions_path, entry)
                resolutions.append(entry)
            results.append({**base, "status": "escalated", "details": entry["details"]})
            continue

        handler = pick_handler(blocker)
        if handler is None:
            results.append({**base, "status": "skipped",
                            "details": "No handler matched — skipping"})
            continue

        cfg = _service_cfg(resolvers, service)
        status, details = handler(blocker, cfg, check_only, ctx)
        entry = {
            "time": now_iso(), "service": service, "issue": issue,
            "handler": handler.__name__, "status": status, "details": details,
            "attempt": attempts + 1,
        }
        if not check_only and status != "check":
            _append_jsonl(resolutions_path, entry)
            resolutions.append(entry)
            if attempts + 1 >= MAX_ATTEMPTS and status == "failed":
                esc = {
                    "time": now_iso(), "service": service, "issue": issue,
                    "handler": "escalation", "status": "escalated",
                    "details": f"Escalated after {attempts + 1} failed attempts",
                    "attempt": attempts + 1,
                }
                _append_jsonl(resolutions_path, esc)
                resolutions.append(esc)
                results.append({**base, "status": "escalated", "details": esc["details"]})
                continue
        results.append({**base, "status": status, "details": details,
                        "handler": handler.__name__, "attempt": attempts + 1})

    return results
