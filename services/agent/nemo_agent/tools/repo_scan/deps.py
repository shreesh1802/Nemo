"""Dependency vulnerability lookup against OSV.dev (free, no API key)."""
import json
import re
from pathlib import Path

import httpx

OSV_BATCH = "https://api.osv.dev/v1/querybatch"
OSV_VULN = "https://api.osv.dev/v1/vulns/{}"
MAX_DETAIL_LOOKUPS = 25


def parse_requirements(path: Path) -> list[tuple[str, str, str]]:
    """Return (ecosystem, name, version) for pinned requirements only."""
    out = []
    for line in path.read_text(errors="ignore").splitlines():
        m = re.match(r"^\s*([A-Za-z0-9_.\-]+)(?:\[[^\]]*\])?\s*==\s*([A-Za-z0-9_.\-+!]+)", line)
        if m:
            out.append(("PyPI", m.group(1), m.group(2)))
    return out


def parse_package_json(path: Path) -> list[tuple[str, str, str]]:
    try:
        data = json.loads(path.read_text(errors="ignore"))
    except json.JSONDecodeError:
        return []
    out = []
    for section in ("dependencies", "devDependencies"):
        for name, spec in (data.get(section) or {}).items():
            version = re.sub(r"^[\^~>=<\s]+", "", str(spec))
            if re.match(r"^\d+\.\d+\.\d+", version):
                out.append(("npm", name, version.split(" ")[0]))
    return out


def collect(root: Path) -> list[tuple[str, str, str, str]]:
    """Return (ecosystem, name, version, manifest) for every manifest under root."""
    found = []
    for manifest in root.rglob("*"):
        if any(p in {"node_modules", ".git", ".venv", "venv"} for p in manifest.parts):
            continue
        if manifest.name == "requirements.txt":
            parsed = parse_requirements(manifest)
        elif manifest.name == "package.json":
            parsed = parse_package_json(manifest)
        else:
            continue
        rel = str(manifest.relative_to(root))
        found += [(e, n, v, rel) for e, n, v in parsed]
    return found


def _severity(vuln: dict) -> str:
    for entry in vuln.get("database_specific", {}).get("severity", ""), "":
        if str(entry).lower() in {"critical", "high", "moderate", "low"}:
            return "medium" if str(entry).lower() == "moderate" else str(entry).lower()
    return "high"  # unknown severity: treat as high rather than hide it


async def lookup(deps: list[tuple[str, str, str, str]]) -> tuple[list[dict], str | None]:
    """Return (findings, error). An unreachable OSV never fails the whole scan."""
    if not deps:
        return [], None
    unique = list({(e, n, v): m for e, n, v, m in deps}.items())[:500]
    queries = [{"package": {"name": n, "ecosystem": e}, "version": v} for (e, n, v), _ in unique]
    findings: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(OSV_BATCH, json={"queries": queries})
            resp.raise_for_status()
            results = resp.json().get("results", [])
            detail_budget = MAX_DETAIL_LOOKUPS
            for ((eco, name, version), manifest), result in zip(unique, results):
                for v in result.get("vulns", [])[:3]:
                    summary, sev = "", "high"
                    if detail_budget > 0:
                        detail_budget -= 1
                        d = await client.get(OSV_VULN.format(v["id"]))
                        if d.status_code == 200:
                            detail = d.json()
                            summary = detail.get("summary", "")
                            sev = _severity(detail)
                    findings.append(
                        {
                            "type": "dependency",
                            "severity": sev,
                            "rule": v["id"],
                            "file": manifest,
                            "line": 0,
                            "message": f"{name} {version} ({eco}): {summary or 'known vulnerability'}",
                            "fix": f"Upgrade {name}; see https://osv.dev/{v['id']}",
                        }
                    )
    except (httpx.HTTPError, ValueError) as exc:
        return findings, f"dependency check incomplete: {type(exc).__name__}"
    return findings, None
