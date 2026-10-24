import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    id: str
    severity: str  # critical | high | medium | low
    pattern: re.Pattern
    message: str
    fix: str
    exts: frozenset[str]


def _r(id, severity, pattern, message, fix, exts):
    return Rule(id, severity, re.compile(pattern), message, fix, frozenset(exts))


PY = {".py"}
JS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}

CODE_RULES = [
    _r("py-eval", "high", r"\beval\s*\(", "eval() runs arbitrary code.",
       "Use ast.literal_eval or a real parser.", PY),
    _r("py-exec", "high", r"\bexec\s*\(", "exec() runs arbitrary code.",
       "Avoid dynamic code execution.", PY),
    _r("py-pickle", "high", r"\bpickle\.loads?\s*\(", "Unpickling untrusted data can execute code.",
       "Use JSON, or only unpickle data you produced and signed.", PY),
    _r("py-yaml-load", "high", r"\byaml\.load\s*\((?![^)]*Safe)", "yaml.load without SafeLoader can construct arbitrary objects.",
       "Use yaml.safe_load.", PY),
    _r("py-shell-true", "high", r"subprocess\.\w+\([^)]*shell\s*=\s*True", "shell=True enables command injection.",
       "Pass an argument list and leave shell off.", PY),
    _r("py-os-system", "medium", r"\bos\.(system|popen)\s*\(", "Shell command built as a string.",
       "Use subprocess with an argument list.", PY),
    _r("py-weak-hash", "medium", r"hashlib\.(md5|sha1)\s*\(", "MD5/SHA-1 are broken for security use.",
       "Use SHA-256 or better; use bcrypt/argon2 for passwords.", PY),
    _r("py-tls-off", "high", r"verify\s*=\s*False", "TLS certificate verification disabled.",
       "Remove verify=False and fix the certificate instead.", PY),
    _r("py-sql-concat", "high",
       r"\.execute\s*\(\s*(f[\"']|[\"'][^\"']*[\"']\s*(%|\+)|[^)]*\.format\()",
       "SQL built by string formatting; likely SQL injection.",
       "Use parameterized queries.", PY),
    _r("js-eval", "high", r"\beval\s*\(|new\s+Function\s*\(", "Dynamic code execution.",
       "Remove eval/new Function; parse data instead.", JS),
    _r("js-innerhtml", "medium", r"\.innerHTML\s*=|dangerouslySetInnerHTML|document\.write\s*\(",
       "Writing raw HTML can cause XSS.", "Use textContent or sanitize with DOMPurify.", JS),
    _r("js-exec-template", "high", r"child_process|\bexec(Sync)?\s*\(\s*`",
       "Shell command built from a template string.", "Use execFile with an argument array.", JS),
    _r("js-tls-off", "high", r"rejectUnauthorized\s*:\s*false|NODE_TLS_REJECT_UNAUTHORIZED",
       "TLS verification disabled.", "Keep verification on.", JS),
]


# Secret patterns: (id, severity, regex, message)
SECRET_PATTERNS = [
    ("aws-access-key", "critical", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b"), "AWS access key ID."),
    ("github-token", "critical", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"), "GitHub token."),
    ("private-key", "critical", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY"), "Private key committed."),
    ("slack-token", "high", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "Slack token."),
    ("google-api-key", "high", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), "Google API key."),
    ("stripe-live-key", "critical", re.compile(r"\b[sr]k_live_[0-9A-Za-z]{20,}\b"), "Stripe live key."),
    ("tavily-key", "high", re.compile(r"\btvly-[A-Za-z0-9-]{16,}\b"), "Tavily API key."),
]

GENERIC_SECRET = re.compile(
    r"""(?ix)(api[_-]?key|secret|token|passwd|password|auth)\w*["']?\s*[:=]\s*["']([^"'\s]{12,})["']"""
)
PLACEHOLDER = re.compile(r"(?i)example|changeme|your[_-]|xxx|<.*>|\$\{|%\(|dummy|placeholder|test|\*{3,}")


def redact(value: str) -> str:
    return value[:4] + "****" if len(value) > 4 else "****"
