import asyncio
from pathlib import Path

from . import deps
from .fetch import FetchError, resolve
from .rules import CODE_RULES, GENERIC_SECRET, PLACEHOLDER, SECRET_PATTERNS, redact

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "dist", "build", "__pycache__",
             "vendor", ".next", "target", ".idea", ".tox"}
MAX_FILE_BYTES = 1_000_000
MAX_FILES = 5000
MAX_REPORTED = 30
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _iter_files(root: Path):
    count = 0
    for path in root.rglob("*"):
        if not path.is_file() or any(p in SKIP_DIRS for p in path.relative_to(root).parts):
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        count += 1
        if count > MAX_FILES:
            return
        yield path


def scan_files(root: Path) -> tuple[list[dict], int]:
    """Static scan of source files. Pure function over the filesystem; runs nothing."""
    findings: list[dict] = []
    scanned = 0
    for path in _iter_files(root):
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if b"\x00" in raw[:2048]:
            continue  # binary
        text = raw.decode("utf-8", errors="ignore")
        scanned += 1
        rel = str(path.relative_to(root))
        ext = path.suffix.lower()
        rules = [r for r in CODE_RULES if ext in r.exts]

        for lineno, line in enumerate(text.splitlines(), 1):
            if len(line) > 2000:
                continue
            for rule in rules:
                if rule.pattern.search(line):
                    findings.append({"type": "code", "severity": rule.severity, "rule": rule.id,
                                     "file": rel, "line": lineno, "message": rule.message,
                                     "fix": rule.fix})
            for rid, sev, pat, msg in SECRET_PATTERNS:
                m = pat.search(line)
                if m:
                    findings.append({"type": "secret", "severity": sev, "rule": rid, "file": rel,
                                     "line": lineno, "message": f"{msg} ({redact(m.group(0))})",
                                     "fix": "Revoke the credential, remove it from history, and load it from the environment."})
            g = GENERIC_SECRET.search(line)
            if g and not PLACEHOLDER.search(g.group(2)):
                findings.append({"type": "secret", "severity": "medium", "rule": "generic-secret",
                                 "file": rel, "line": lineno,
                                 "message": f"Possible hardcoded secret in `{g.group(1)}` ({redact(g.group(2))})",
                                 "fix": "Move to an environment variable or secret manager."})
    return findings, scanned


def summarize(findings: list[dict], scanned: int, notes: list[str]) -> dict:
    findings = sorted(findings, key=lambda f: (SEVERITY_ORDER[f["severity"]], f["file"], f["line"]))
    counts = {s: sum(1 for f in findings if f["severity"] == s) for s in SEVERITY_ORDER}
    return {
        "files_scanned": scanned,
        "counts": counts,
        "total": len(findings),
        "findings": findings[:MAX_REPORTED],
        "truncated": max(0, len(findings) - MAX_REPORTED),
        "notes": notes,
    }


async def scan_repo(args: dict) -> dict:
    source = str(args.get("source", "")).strip()
    if not source:
        return {"error": "source is required (a local folder or an https git URL)"}
    try:
        async with resolve(source) as root:
            findings, scanned = await asyncio.to_thread(scan_files, root)
            dep_findings, dep_error = await deps.lookup(deps.collect(root))
    except FetchError as exc:
        return {"error": str(exc)}
    notes = [dep_error] if dep_error else []
    return summarize(findings + dep_findings, scanned, notes)
