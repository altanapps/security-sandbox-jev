"""Seed data for Larkspur.

Two ways to get an org:

- `python -m org.seed build`  — run the generator (story.yaml + Faker, fixed seed),
  write the JSON snapshot to org/seed/snapshot/, and load it into SQLite.
- `python -m org.seed load`   — load the committed JSON snapshot into SQLite
  without running the generator.

The snapshot is the canonical dataset. The generator is how it was made.
"""
