import pytest

from nemo_agent.tools.repo_scan import deps
from nemo_agent.tools.repo_scan.fetch import FetchError, resolve
from nemo_agent.tools.repo_scan.scan import scan_files, scan_repo, summarize

FAKE_AWS = "AKIA" + "ABCDEFGHIJKLMNOP"  # split so this file isn't itself flagged


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "app.py").write_text(
        "import pickle, subprocess, yaml\n"
        "data = pickle.loads(blob)\n"
        "subprocess.run(cmd, shell=True)\n"
        'cur.execute(f"SELECT * FROM users WHERE id={uid}")\n'
        "cfg = yaml.load(open('c.yml'))\n"
        f'KEY = "{FAKE_AWS}"\n'
        'password = "hunter2hunter2hunter2"\n'
        'api_key = "your_api_key_here_please"\n'  # placeholder: must not be flagged
    )
    (tmp_path / "web.js").write_text("el.innerHTML = userInput;\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "bad.py").write_text("eval(x)\n")  # must be skipped
    (tmp_path / "requirements.txt").write_text("requests==2.19.1\nflask>=2.0\n")
    return tmp_path


def test_finds_expected_issues_and_skips_node_modules(repo):
    findings, scanned = scan_files(repo)
    rules = {f["rule"] for f in findings}
    assert {"py-pickle", "py-shell-true", "py-sql-concat", "py-yaml-load",
            "aws-access-key", "generic-secret", "js-innerhtml"} <= rules
    assert not any("node_modules" in f["file"] for f in findings)
    assert scanned == 3  # app.py, web.js, requirements.txt


def test_placeholder_secret_not_flagged_and_secrets_redacted(repo):
    findings, _ = scan_files(repo)
    generic = [f for f in findings if f["rule"] == "generic-secret"]
    assert len(generic) == 1 and "hunter2hunter2" not in generic[0]["message"]
    aws = next(f for f in findings if f["rule"] == "aws-access-key")
    assert FAKE_AWS not in aws["message"]


def test_summary_sorted_by_severity(repo):
    findings, scanned = scan_files(repo)
    summary = summarize(findings, scanned, [])
    sevs = [f["severity"] for f in summary["findings"]]
    assert sevs == sorted(sevs, key=["critical", "high", "medium", "low"].index)
    assert summary["counts"]["critical"] >= 1


def test_requirements_only_pinned(repo):
    parsed = deps.parse_requirements(repo / "requirements.txt")
    assert parsed == [("PyPI", "requests", "2.19.1")]


def test_package_json_strips_ranges(tmp_path):
    (tmp_path / "package.json").write_text('{"dependencies": {"lodash": "^4.17.4", "x": "latest"}}')
    assert deps.parse_package_json(tmp_path / "package.json") == [("npm", "lodash", "4.17.4")]


async def test_rejects_non_https_and_missing_dir(tmp_path):
    with pytest.raises(FetchError):
        async with resolve("http://example.com/x.git"):
            pass
    result = await scan_repo({"source": str(tmp_path / "nope")})
    assert "error" in result


def _git(tmp_path, *args):
    import subprocess

    subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)


def test_gitignored_files_are_skipped(tmp_path):
    _git(tmp_path, "init", "-q")
    (tmp_path / ".gitignore").write_text(".env\n")
    (tmp_path / ".env").write_text(f"KEY={FAKE_AWS}\n")  # ignored: must not be reported
    (tmp_path / "app.py").write_text(f'KEY = "{FAKE_AWS}"\n')  # not ignored: must be reported
    findings, _ = scan_files(tmp_path)
    assert {f["file"] for f in findings} == {"app.py"}


def test_untracked_but_not_ignored_files_are_still_scanned(tmp_path):
    _git(tmp_path, "init", "-q")
    (tmp_path / "new.py").write_text("eval(user_input)\n")
    findings, _ = scan_files(tmp_path)
    assert any(f["rule"] == "py-eval" for f in findings)


def test_inline_ignore_and_ignore_file(tmp_path):
    (tmp_path / "a.py").write_text("eval(x)  # nemo-scan: ignore\neval(y)\n")
    (tmp_path / "rules.py").write_text("eval(z)\n")
    (tmp_path / ".nemoscanignore").write_text("# comment\nrules.py\n")
    findings, _ = scan_files(tmp_path)
    assert [(f["file"], f["line"]) for f in findings] == [("a.py", 2)]


def test_code_findings_in_tests_are_low_but_secrets_are_not(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text(f'eval(x)\nKEY = "{FAKE_AWS}"\n')
    findings, _ = scan_files(tmp_path)
    by_rule = {f["rule"]: f for f in findings}
    assert by_rule["py-eval"]["severity"] == "low" and "test code" in by_rule["py-eval"]["message"]
    assert by_rule["aws-access-key"]["severity"] == "critical"


def test_attribute_eval_and_exec_are_not_flagged(tmp_path):
    (tmp_path / "m.py").write_text("model.eval()\npattern.exec(s)\nast.literal_eval(s)\nresult = eval(s)\n")
    findings, _ = scan_files(tmp_path)
    assert [f["line"] for f in findings] == [4]
