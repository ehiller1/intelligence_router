"""
Migration sanity checks that don't require a live Postgres instance (this
sandbox cannot run one -- Postgres needs a SysV shared-memory segment even
in `shared_memory_type=mmap` mode, via IpcMemoryCreate's small control
segment, and this sandbox blocks `shmget` unconditionally; see
ir_controlplane/migrations/README.md).

What these tests DO verify:
  - every migration file parses as a sequence of complete SQL statements
    (sqlparse-level: balanced parens, terminated statements)
  - every enum-shaped CHECK constraint's allowed values match ir_core.types
    exactly, so the database schema and the application's lattice types
    cannot silently drift apart
  - migrations apply in numeric order and every forward reference (a FK to
    a table defined in a later-numbered file) is caught

What they do NOT verify: that the SQL is accepted by a real Postgres
server. That must happen in CI against an actual instance before this
schema is relied on.
"""
import re
from pathlib import Path

import pytest
import sqlparse

from ir_core.types import CapabilityTier, GovernanceTier, Posture, PrivacyClass

MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"
MIGRATION_FILES = sorted(MIGRATIONS_DIR.glob("*.sql"))


def _sql_texts():
    return {p.name: p.read_text() for p in MIGRATION_FILES}


# ---------------------------------------------------------------------------
# Basic structural sanity: every file parses into complete statements.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", MIGRATION_FILES, ids=lambda p: p.name)
def test_migration_file_parses_as_sql_statements(path):
    text = path.read_text()
    statements = sqlparse.parse(text)
    assert statements, f"{path.name}: no SQL statements found"
    for stmt in statements:
        stripped = stmt.value.strip()
        if not stripped or stripped.startswith("--"):
            continue
        assert stripped.endswith(";"), (
            f"{path.name}: statement not terminated with ';':\n{stripped[:120]}"
        )
    # Balanced parens is implied by sqlparse not raising, but double check
    # explicitly since sqlparse is a lenient tokenizer, not a validator.
    depth = 0
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
    assert depth == 0, f"{path.name}: unbalanced parentheses (net depth {depth})"


def test_migrations_are_numbered_and_applied_in_order():
    names = [p.name for p in MIGRATION_FILES]
    numbers = [int(re.match(r"^(\d+)_", n).group(1)) for n in names]
    assert numbers == sorted(numbers), f"Migration files out of numeric order: {names}"
    assert len(set(numbers)) == len(numbers), f"Duplicate migration numbers: {names}"


# ---------------------------------------------------------------------------
# Enum-shaped CHECK constraints must match ir_core.types exactly. This is
# the test that actually catches drift between the schema and the code --
# far more valuable than a live Postgres accepting the DDL syntactically.
# ---------------------------------------------------------------------------

def _extract_check_in_values(sql_text: str, column_name: str) -> "set[str]":
    """
    Finds `<column_name> ... CHECK (<column_name> IN ('a', 'b', ...))` (in
    any of the styles used across these files: inline column CHECK, or a
    named CONSTRAINT ... CHECK) and returns the quoted values as a set.
    """
    pattern = re.compile(
        rf"{re.escape(column_name)}\b[^,]*?\bIN\s*\(([^)]*)\)",
        re.IGNORECASE | re.DOTALL,
    )
    values = set()
    for match in pattern.finditer(sql_text):
        group = match.group(1)
        for lit in re.findall(r"'([^']*)'", group):
            if lit != "NULL":  # NULL sometimes appears as a literal via ", NULL)" style checks
                values.add(lit)
    return values


ALL_SQL = "\n".join(_sql_texts().values())


def test_governance_tier_check_matches_ir_core_types():
    db_values = _extract_check_in_values(ALL_SQL, "governance_tier")
    code_values = {t.name.lower() for t in GovernanceTier}
    assert db_values == code_values, (
        f"ir_core.types.GovernanceTier {code_values} != SQL CHECK values {db_values}"
    )


def test_privacy_class_check_matches_ir_core_types():
    db_values = _extract_check_in_values(ALL_SQL, "privacy_class")
    code_values = {p.name for p in PrivacyClass}  # P0..P3, already correctly cased
    assert db_values == code_values, (
        f"ir_core.types.PrivacyClass {code_values} != SQL CHECK values {db_values}"
    )


def test_privacy_ceiling_check_matches_ir_core_types():
    db_values = _extract_check_in_values(ALL_SQL, "privacy_ceiling")
    code_values = {p.name for p in PrivacyClass}
    assert db_values == code_values


def test_posture_check_matches_ir_core_types():
    db_values = _extract_check_in_values(ALL_SQL, "posture")
    code_values = {p.name.lower() for p in Posture}
    assert db_values == code_values, (
        f"ir_core.types.Posture {code_values} != SQL CHECK values {db_values}"
    )


def test_capability_tier_check_matches_ir_core_types():
    db_values = _extract_check_in_values(ALL_SQL, "capability_tier")
    code_values = {t.name.lower() for t in CapabilityTier}
    assert db_values == code_values, (
        f"ir_core.types.CapabilityTier {code_values} != SQL CHECK values {db_values}"
    )


# ---------------------------------------------------------------------------
# No forward references: a table referenced by FK must be defined in an
# equal-or-earlier-numbered file.
# ---------------------------------------------------------------------------

def test_no_forward_references_across_migrations():
    texts = _sql_texts()
    ordered_names = [p.name for p in MIGRATION_FILES]

    defined_by_file = {}
    for name in ordered_names:
        defined_by_file[name] = set(
            re.findall(r"CREATE TABLE (\w+)", texts[name], re.IGNORECASE)
        )

    seen_tables = set()
    for name in ordered_names:
        referenced = set(re.findall(r"REFERENCES\s+(\w+)\s*\(", texts[name], re.IGNORECASE))
        # A file may reference tables it defines itself or any earlier file.
        available = seen_tables | defined_by_file[name]
        missing = referenced - available
        assert not missing, f"{name} references undefined table(s): {missing}"
        seen_tables |= defined_by_file[name]


def test_exactly_one_of_ledger_entry_or_digest_batch_constraint_present():
    """Decision R6's coverage rule has a named constraint -- confirm it exists."""
    text = (MIGRATIONS_DIR / "006_routing_decisions.sql").read_text()
    assert "ck_ledger_xor_digest" in text
