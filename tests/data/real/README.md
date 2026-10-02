# Real-world test files

Drop real JSON language files here (any number, any size). A `.json.meta` sidecar beside one is
read too. `tests/check_core_corpus.py` runs every `*.json` in this folder through load, an
unchanged save, a one-entry edit, a one-entry delete and a merge into itself, always on a copy, so
these files are never changed.

Everything in this folder except this README is gitignored: the files stay on your machine and
never reach the repository. With no files here the check passes and notes that it was skipped.

Each run's report (`tests/reports/latest.md`) lists every file with its string count and
load/save time under "Notes", and names any file that does not round-trip in its own style.
