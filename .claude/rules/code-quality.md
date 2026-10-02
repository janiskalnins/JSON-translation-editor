---
alwaysApply: true
---

# Code Quality

## Anti-defaults (counter common Claude tendencies)

- No premature abstractions. Three similar lines beats a helper used once.
- Don't add features or improvements beyond what was asked.
- Don't refactor adjacent code while fixing a bug.
- No dead code or commented-out blocks. Git has history.
- WHY comments, never WHAT. If code needs a "what" comment, rename instead.
- API docs at module boundaries only, not every internal function.

## Naming

- Files: `snake_case.py`. Classes: `PascalCase`. Functions/methods/variables: `snake_case`. Constants: `SCREAMING_SNAKE`.
- Booleans: `is_` / `has_` / `should_` / `can_` prefix. Functions: verb-first (`get_user`, `build_xml`).
- Factories: `create_*`. Converters: `to_*`. Predicates: `is_*` / `has_*`.
- Abbreviations only when universally known (`id`, `url`, `api`, `db`). Acronyms as words: `user_id`, not `userID`.

## Code Markers

`TODO(author): desc (#issue)` for planned work. `FIXME(author): desc (#issue)` for known bugs. `HACK(author): desc (#issue)` for ugly workarounds (explain the proper fix). `NOTE: desc` for non-obvious context. Owner and issue link required. Never `XXX`, `TEMP`, `REMOVEME`.

## File Organization

- Imports: builtins, external, internal, relative, types. Blank line between groups.
- Exports: named over default. One component or class per file.
- Function order: public API first, then helpers in call order.
