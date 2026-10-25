import asyncio
import fnmatch
import re
import subprocess
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
INLINE_IGNORE = "nemo-scan: ignore"
IGNORE_FILE = ".nemoscanignore"
# Code patterns in test code are rarely exploitable, so they are reported as low.
TEST_PATH = re.compile(
    r"(^|/)(tests?|__tests__|fixtures?|spec)/|(^|/)test_[^/]*\.py$|\.(test|spec)\.[jt]sx?$"
)


def _git_files(root: Path):
    """Files git considers part of the project: tracked, or untracked but not ignored.
    Returns None when root is not a usable git checkout."""
    if not (root / ".git").exists():
        return None
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            capture_output=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    names = [n for n in proc.stdout.decode("utf-8", errors="ignore").split(chr(0)) if n]
    return [root / n for n in names]


def _load_ignore_patterns(root: Path) -> list[str]:
    f = root / IGNORE_FILE
    if not f.is_file():
        return []
    lines = f.read_text(encoding="utf-8", errors="ignore").splitlines()
    return [l.strip() for l in lines if l.strip() and not l.lstrip().startswith("#")]


def _is_ignored(rel: str, patterns: list[str]) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(name, p) or rel.startswith(p.rstrip("/") + "/")
               for p in patterns)


def _iter_files(root: Path):
    patterns = _load_ignore_patterns(root)
    candidates = _git_files(root)
    if candidates is None:
        candidates = root.rglob("*")  # not a git repo: walk everything
    count = 0
    for path in candidates:
        try:
            rel_parts = path.relative_to(root).parts
        except ValueError:
            continue
        if any(p in SKIP_DIRS for p in rel_parts) or not path.is_file():
            continue
        if _is_ignored("/".join(rel_parts), patterns):
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

        in_tests = bool(TEST_PATH.search(rel.replace("\\", "/")))
        file_findings_start = len(findings)
        for lineno, line in enumerate(text.splitlines(), 1):
            if len(line) > 2000 or INLINE_IGNORE in line:
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
        if in_tests:
            for f in findings[file_findings_start:]:
                if f["type"] == "code":
                    f["severity"], f["message"] = "low", f["message"] + " (in test code)"
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
