"""Run every tests/check_*.py, each in its own process, and summarise.

Usage:
  python tests/run_all.py                          run every check
  python tests/run_all.py merge_compare combobox   run only these (with or without check_ / .py)
  python tests/run_all.py --trigger pre-commit     name what started the run in the report

Exit code: 0 when every selected check passed, 1 when one failed or timed out, 2 for an unknown
name. Each check runs in a fresh temporary working folder, so the files a check writes relative to
its working directory (error_log.txt, settings, backups) never land in the repo, and without
QT_QPA_PLATFORM, so each check uses its own default (offscreen).

Every run also writes a Markdown report to tests/reports/ (gitignored): run_<date>_<time>.md and a
copy as latest.md, keeping the newest REPORTS_KEEP. A report that cannot be written prints a
warning and never changes the exit code.
"""

import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from importlib import metadata
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple

TESTS_DIR = Path(__file__).resolve().parent
REPO_DIR = TESTS_DIR.parent
REPORTS_DIR = TESTS_DIR / "reports"
REPORTS_KEEP = 30
TIMEOUT_S = 300
TAIL_LINES = 20
DETAIL_INDENT = "        "
# \r?: a check's output reaches the pipe with CRLF line endings on Windows.
_TESTS_RUN_RE = re.compile(r"^(\d+) test\(s\) run\r?$", re.MULTILINE)


class CheckResult(NamedTuple):
    name: str
    status: str      # PASS, FAIL or TIMEOUT
    seconds: float
    output: str


def short_name(name: str) -> str:
    """'tests/check_merge_compare.py', 'check_merge_compare' and 'merge_compare' -> 'merge_compare'."""
    name = Path(name).name
    if name.endswith(".py"):
        name = name[:-3]
    if name.startswith("check_"):
        name = name[len("check_"):]
    return name


def discover() -> List[Path]:
    return sorted(TESTS_DIR.glob("check_*.py"))


def select(checks: List[Path], names: List[str]) -> Optional[List[Path]]:
    """The checks named in *names*, in that order; None (after printing why) if one is unknown."""
    by_name = {short_name(p.name): p for p in checks}
    wanted = [short_name(n) for n in names]
    unknown = [n for n in wanted if n not in by_name]
    if unknown:
        print("Unknown check(s): " + ", ".join(unknown))
        print("Valid names: " + ", ".join(sorted(by_name)))
        return None
    return [by_name[n] for n in wanted]


def run_check(script: Path) -> Tuple[str, float, str]:
    """Run *script* in a throwaway working folder; return (status, seconds, combined output)."""
    env = dict(os.environ)
    env.pop("QT_QPA_PLATFORM", None)
    # A check's print() of non-ASCII text must not fail on a cp1252 pipe.
    env["PYTHONIOENCODING"] = "utf-8"
    workdir = tempfile.mkdtemp(prefix="xte_check_")
    start = time.monotonic()
    try:
        try:
            proc = subprocess.run([sys.executable, str(script)], cwd=workdir, env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  timeout=TIMEOUT_S)
            status = "PASS" if proc.returncode == 0 else "FAIL"
            raw = proc.stdout
        except subprocess.TimeoutExpired as exc:
            status = "TIMEOUT"
            raw = exc.stdout or b""
        seconds = time.monotonic() - start
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return status, seconds, raw.decode("utf-8", errors="replace")


def failure_details(output: str) -> List[str]:
    """The check's own 'FAIL <label>' or 'FAIL: <label>' lines, or the tail of its output when it printed none
    (a crash or traceback). 'FAILED: N failure(s)' is the summary, not a detail."""
    lines = output.splitlines()
    fails = [line for line in lines if line.startswith("FAIL") and not line.startswith("FAILED")]
    return fails or lines[-TAIL_LINES:]


def note_lines(output: str) -> List[str]:
    """The text of the check's 'NOTE <text>' lines: information for the report, not failures."""
    return [line[len("NOTE "):] for line in output.splitlines() if line.startswith("NOTE ")]


def tests_run(output: str) -> Optional[int]:
    """The 'N test(s) run' count a unittest-based check prints; None for a check that has none."""
    m = _TESTS_RUN_RE.search(output)
    return int(m.group(1)) if m else None


# ── Report ──────────────────────────────────────────────────────────────────

def _git(*args: str) -> str:
    try:
        proc = subprocess.run(["git", *args], cwd=REPO_DIR, capture_output=True, timeout=10)
        return proc.stdout.decode("utf-8", errors="replace").strip() if proc.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _version(package: str) -> str:
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return "not installed"


def collect_meta(trigger: str, selection: str) -> Dict[str, str]:
    """What the report header shows: when, why, which checks, and the code and tools it ran on."""
    status = _git("status", "--porcelain")
    return {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "trigger": trigger,
        "selection": selection,
        "branch": _git("branch", "--show-current") or "unknown",
        "commit": _git("log", "-1", "--format=%h %s") or "unknown",
        # The checks test the working tree, so a run with uncommitted edits did not test the commit.
        "uncommitted": "yes" if status else "no",
        "python": platform.python_version(),
        "pyside6": _version("PySide6"),
    }


_META_LABELS = [("time", "Time"), ("trigger", "Trigger"), ("selection", "Checks"),
                ("branch", "Branch"), ("commit", "Commit"),
                ("uncommitted", "Uncommitted changes"), ("python", "Python"),
                ("pyside6", "PySide6")]


def build_report(results: List[CheckResult], meta: Dict[str, str], total_seconds: float) -> str:
    """The Markdown report: header, summary, one table row per check, a Notes section with the
    checks' NOTE lines and a Failures section with each failed check's details, each only when
    there are any."""
    passed = sum(1 for r in results if r.status == "PASS")
    lines = ["# Test run report", ""]
    lines += [f"- **{label}:** {meta.get(key, '')}" for key, label in _META_LABELS]
    lines += ["", f"**{passed} passed, {len(results) - passed} failed** ({total_seconds:.1f} s)", "",
              "| Check | Result | Time | Tests |", "|---|---|---:|---:|"]
    for r in results:
        count = tests_run(r.output)
        lines.append(f"| {r.name} | {r.status} | {r.seconds:.1f} s | "
                     f"{count if count is not None else '—'} |")
    noted = [(r.name, note_lines(r.output)) for r in results if note_lines(r.output)]
    if noted:
        lines += ["", "## Notes"]
        for name, notes in noted:
            lines += ["", f"### {name}", "", *(f"- {note}" for note in notes)]
    failed = [r for r in results if r.status != "PASS"]
    if failed:
        lines += ["", "## Failures"]
        for r in failed:
            lines += ["", f"### {r.name}", "", "```", *failure_details(r.output), "```"]
    return "\n".join(lines) + "\n"


def write_report(text: str, folder: Path, now: datetime, keep: int = REPORTS_KEEP) -> Path:
    """Write *text* as run_<date>_<time>.md and latest.md in *folder*, then delete all but the
    newest *keep* run_*.md files. Returns the timestamped file; raises OSError on failure."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"run_{now.strftime('%Y-%m-%d_%H-%M-%S')}.md"
    path.write_text(text, encoding="utf-8")
    (folder / "latest.md").write_text(text, encoding="utf-8")
    # The timestamp in the name sorts in time order.
    for old in sorted(folder.glob("run_*.md"))[:-keep]:
        old.unlink()
    return path


def _pop_option(argv: List[str], option: str, default: str) -> str:
    """Remove '<option> <value>' from *argv* and return the value (*default* when absent)."""
    if option in argv:
        i = argv.index(option)
        value = argv[i + 1] if i + 1 < len(argv) else default
        del argv[i:i + 2]
        return value
    return default


def main(argv: List[str]) -> int:
    sys.stdout.reconfigure(errors="replace")
    argv = list(argv)
    trigger = _pop_option(argv, "--trigger", "manual")
    checks = discover()
    if argv:
        checks = select(checks, argv)
        if checks is None:
            return 2
    results: List[CheckResult] = []
    start = time.monotonic()
    for script in checks:
        status, seconds, output = run_check(script)
        results.append(CheckResult(script.stem, status, seconds, output))
        print(f"{status:<7} {seconds:5.1f}s  {script.stem}", flush=True)
        if status == "PASS":
            continue
        for line in failure_details(output):
            print(DETAIL_INDENT + line)
    total = time.monotonic() - start
    passed = sum(1 for r in results if r.status == "PASS")
    failed = len(results) - passed
    print(f"{passed} passed, {failed} failed ({total:.1f} s)")
    selection = ", ".join(r.name for r in results) if argv else "all checks"
    try:
        report = write_report(build_report(results, collect_meta(trigger, selection), total),
                              REPORTS_DIR, datetime.now())
        print(f"Report: {report.relative_to(REPO_DIR) if report.is_relative_to(REPO_DIR) else report}")
    except OSError as e:
        print(f"Warning: the report could not be written ({e})")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
