---
inclusion: always
---
# Product: Grave Digger

Grave Digger raises legacy utility-billing code from the dead. It reads an old
Oracle PL/SQL package, explains in plain English what it really does, maps what
depends on what, ports it to modern Python, and PROVES the port is correct:
property-based tests bill thousands of random customers in Oracle and in Python
and the bills must match to the paisa. A mismatch is a "ghost": the smallest
input where the two disagree.

## Who it is for
Teams migrating decades-old PL/SQL (utilities, banks, government) who cannot
prove the new system bills exactly like the old one.

## The five stages
1. Exhume: load and split a PL/SQL package.
2. Autopsy: business rules in plain English + dependency graph. Every rule must
   cite the code line it came from.
3. Resurrect: one Kiro spec per legacy unit, then a typed Python port.
4. Prove: Hypothesis equivalence tests, Oracle vs Python.
5. Report: migration certificate (rules, cases, ghosts found and fixed).

## Hard rules
- Synthetic or open-source legacy code ONLY. Never real employer, client or
  utility code, data, tariffs or customer names.
- This is a NEW project, started Nov 13, 2026. Do not copy code from older
  projects (e.g. Loss Lens, Utility Data Copilot).
- The /.kiro folder is committed at the repo root. Never add it to .gitignore.
- Hackathon: Kiroween 2026, Resurrection category. Deadline Dec 4, 2026 2 PM PT.

## Voice
- User-facing text is clear, plain English for non-programmers too.
- Halloween theme is light and clever (graveyard, exhume, ghost), never gory.
- Prefer the simplest thing that works and demos well.
