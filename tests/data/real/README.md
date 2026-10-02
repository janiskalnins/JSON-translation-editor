# Real-world test files

Drop real translation XML files here (any number, any size). `tests/check_core_corpus.py` runs
every `*.xml` in this folder through load, an unchanged save, a one-row edit, a one-row delete and
a merge into itself, always on a copy, so these files are never changed.

Everything in this folder except this README is gitignored: the files stay on your machine and
never reach the repository. With no files here the check passes and notes that it was skipped.

Each run's report (`tests/reports/latest.md`) lists every file with its string count, duplicate
groups and load/save time under "Notes".
