"""Check the user docs' relative links, image paths and #anchors.

    python Tools/check_doc_links.py
    python Tools/check_doc_links.py --old-readme <path to the pre-split README.md>

Checks README.md, docs/FEATURES.md and docs/BUILDING.md: every relative link, href, src and
srcset must name an existing file, and every #anchor must match a heading's GitHub slug in the
file it points to. With --old-readme it also lists the old README's headings (bar "Table of
Contents") that none of the three files has. Prints one "FAIL ..." line per problem; exit code 0
means none.
"""
import argparse
import re
import sys
from pathlib import Path
from typing import Dict, Iterator, List, Set

REPO = Path(__file__).resolve().parent.parent
DOC_FILES = ["README.md", "docs/FEATURES.md", "docs/BUILDING.md"]
IGNORED_OLD_HEADINGS = {"Table of Contents"}

_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$")
_MD_LINK_RE = re.compile(r"\]\(<?([^)\s>]+)>?(?:[ \t]+\"[^\"]*\")?\)")
_HTML_ATTR_RE = re.compile(r"\b(?:href|src|srcset)=\"([^\"]+)\"")
_CODE_SPAN_RE = re.compile(r"`[^`]*`")
_EXTERNAL = ("http://", "https://", "mailto:")


def github_slug(heading: str) -> str:
    """GitHub's anchor for a heading: lower case, punctuation dropped, spaces to hyphens."""
    text = re.sub(r"<[^>]+>", "", heading).strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def _lines_outside_fences(text: str) -> Iterator[str]:
    in_fence = False
    for line in text.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            yield line


def headings(text: str) -> List[str]:
    found = []
    for line in _lines_outside_fences(text):
        match = _HEADING_RE.match(line)
        if match:
            found.append(match.group(2))
    return found


def anchors(text: str) -> Set[str]:
    """Every anchor GitHub creates for the headings, with -1, -2 ... on repeats."""
    seen: Dict[str, int] = {}
    result = set()
    for heading in headings(text):
        slug = github_slug(heading)
        count = seen.get(slug, 0)
        result.add(slug if count == 0 else f"{slug}-{count}")
        seen[slug] = count + 1
    return result


def _link_targets(text: str) -> List[str]:
    targets = []
    for line in _lines_outside_fences(text):
        line = _CODE_SPAN_RE.sub("", line)   # a code span is text, not a link
        targets += _MD_LINK_RE.findall(line)
        for value in _HTML_ATTR_RE.findall(line):
            targets.append(value.split()[0])   # srcset "path 2x" -> path
    return [t for t in targets if not t.startswith(_EXTERNAL)]


def check_file(path: Path) -> List[str]:
    problems = []
    for target in _link_targets(path.read_text(encoding="utf-8")):
        file_part, _, anchor = target.partition("#")
        dest = (path.parent / file_part) if file_part else path
        if not dest.exists():
            problems.append(f"{path.name}: missing file {target}")
        elif anchor and dest.suffix == ".md" and anchor not in anchors(
                dest.read_text(encoding="utf-8")):
            problems.append(f"{path.name}: missing anchor {target}")
    return problems


def missing_headings(old_text: str, new_texts: List[str]) -> List[str]:
    present = set()
    for text in new_texts:
        present.update(headings(text))
    return [h for h in headings(old_text)
            if h not in IGNORED_OLD_HEADINGS and h not in present]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Check the user docs' links and anchors.")
    parser.add_argument("--old-readme", type=Path,
                        help="pre-split README.md; list its headings that were not carried over")
    args = parser.parse_args(argv)

    paths = [REPO / name for name in DOC_FILES]
    problems = []
    for path in paths:
        if path.exists():
            problems += check_file(path)
        else:
            problems.append(f"missing doc {path.relative_to(REPO)}")
    if args.old_readme:
        new_texts = [p.read_text(encoding="utf-8") for p in paths if p.exists()]
        old_text = args.old_readme.read_text(encoding="utf-8")
        problems += [f"heading not carried over: {h}"
                     for h in missing_headings(old_text, new_texts)]

    for problem in problems:
        print(f"FAIL {problem}")
    print(f"{'PASSED' if not problems else 'FAILED'}: {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
