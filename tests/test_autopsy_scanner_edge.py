"""Edge cases for the Autopsy scanner on real-world legacy PL/SQL.

Found in review on Nov 14: none of these appear in BILLING_PKG, but they are
common in legacy code that users will paste into Grave Digger. Each one would
put a false table into the dependency graph or a false "business constant"
into the autopsy rules.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from gravedigger.autopsy.scanner import scan
from gravedigger.exhume import load_package

SPEC = """CREATE OR REPLACE PACKAGE edge_pkg AS
  FUNCTION f_x (p_a NUMBER) RETURN NUMBER;
END edge_pkg;
/
"""


def facts_for(body_lines: str, declarations: str = ""):
    body = (
        "CREATE OR REPLACE PACKAGE BODY edge_pkg AS\n"
        "  FUNCTION f_x (p_a NUMBER) RETURN NUMBER IS\n"
        f"{declarations}"
        "  BEGIN\n"
        f"{body_lines}"
        "    RETURN 0;\n"
        "  END f_x;\n"
        "END edge_pkg;\n"
        "/\n"
    )
    (unit,) = load_package(SPEC, body).units
    return scan(unit)


def values(f) -> set[Decimal]:
    return {c.value for c in f.constants}


# ---------------------------------------------------------------- tables


def test_dual_is_not_a_table():
    f = facts_for("    SELECT SYSDATE INTO v_d FROM DUAL;\n", "    v_d DATE;\n")
    assert f.tables_read == set()


def test_extract_from_is_not_a_table():
    f = facts_for("    v_yr := EXTRACT(YEAR FROM v_d);\n", "    v_d DATE;\n    v_yr NUMBER;\n")
    assert f.tables_read == set()


def test_trim_from_is_not_a_table():
    f = facts_for("    v_nm := TRIM(LEADING '0' FROM v_nm);\n", "    v_nm VARCHAR2(20);\n")
    assert f.tables_read == set()


def test_real_tables_still_found_next_to_function_syntax():
    f = facts_for(
        "    SELECT EXTRACT(MONTH FROM rdg_dt) INTO v_m FROM MTR_RDG WHERE ROWNUM = 1;\n"
        "    FOR r IN (SELECT t.x FROM tariff_tbl t JOIN zone_tbl z ON t.z = z.z) LOOP NULL; END LOOP;\n",
        "    v_m NUMBER;\n",
    )
    assert f.tables_read == {"MTR_RDG", "TARIFF_TBL", "ZONE_TBL"}


# ---------------------------------------------------------------- constants


def test_datatype_sizes_are_not_constants():
    f = facts_for(
        "    n_amt := p_a * 0.05;\n",
        "    v_nm  VARCHAR2(100);\n    n_amt NUMBER(12,2);\n    c_cd  CHAR(3);\n",
    )
    found = values(f)
    assert Decimal("0.05") in found
    assert not {Decimal("100"), Decimal("12"), Decimal("2"), Decimal("3")} & found


def test_cast_and_substr_arguments_are_still_constants():
    """Only datatype sizes are excluded, not ordinary function arguments."""
    f = facts_for("    v_s := SUBSTR(v_s, 1, 4);\n", "    v_s VARCHAR2(10);\n")
    assert {Decimal("1"), Decimal("4")} <= values(f)


@pytest.mark.parametrize(
    "code, expected",
    [
        ("    IF p_a < -1 THEN NULL; END IF;\n", Decimal("-1")),
        ("    v_n := -250;\n", Decimal("-250")),
        ("    v_n := ROUND(p_a, -2);\n", Decimal("-2")),
        ("    v_n := p_a * -0.5;\n", Decimal("-0.5")),
    ],
)
def test_negative_literals_keep_their_sign(code, expected):
    f = facts_for(code, "    v_n NUMBER;\n")
    assert expected in values(f)


def test_subtraction_is_not_a_negative_literal():
    f = facts_for("    v_n := p_a - 1;\n    v_n := v_n-2;\n", "    v_n NUMBER;\n")
    found = values(f)
    assert {Decimal("1"), Decimal("2")} <= found
    assert not {Decimal("-1"), Decimal("-2")} & found
