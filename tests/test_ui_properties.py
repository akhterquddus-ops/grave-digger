"""Property tests for gravedigger.ui.views (feature: ui).

Speed constraint: this whole file must run in under 30 seconds with
HYPOTHESIS_PROFILE=ci (2000 examples, fixed seed). No property here runs a
full hunt over golden/cases.json or starts the Streamlit app per example.
Slow or tiny-domain properties carry an explicit @settings(max_examples=...).

tests/test_ui.py is the approved acceptance contract and is not edited.
"""

from __future__ import annotations

import re
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from gravedigger.ui.views import PORT_OF, UNIT_ORDER, legacy_source, python_source, rs

# Money is built from integers (cents), never from floats.
amounts = st.integers(min_value=0, max_value=10**12).map(lambda n: Decimal(n).scaleb(-2))
signed_amounts = st.integers(min_value=-(10**12), max_value=10**12).map(
    lambda n: Decimal(n).scaleb(-2)
)


# Feature: ui, Property 1: Rupee formatting round trip
@given(amounts)
def test_rs_round_trip(amount: Decimal) -> None:
    """**Validates: Requirements 1.1, 1.2, 1.3, 16.1, 16.4**"""
    text = rs(amount)
    assert text.startswith("Rs ")
    body = text[len("Rs "):]
    whole, dot, frac = body.partition(".")
    if amount % 1 != 0:
        assert dot == "." and len(frac) == 2 and frac.isdigit()
    else:
        assert dot == ""
    assert Decimal(body.replace(",", "")) == amount
    assert rs(amount) == text


# Feature: ui, Property 2: Negative amounts put the minus sign first
@given(signed_amounts.filter(lambda x: x != 0))
def test_rs_minus_sign_first(x: Decimal) -> None:
    """**Validates: Requirements 1.4**"""
    if x > 0:
        assert rs(-x) == "-" + rs(x)
    else:
        assert rs(x) == "-" + rs(-x)


# Feature: ui, Requirement 1.5: rs refuses anything that is not a Decimal
def test_rs_rejects_float() -> None:
    """**Validates: Requirements 1.5**"""
    with pytest.raises(TypeError):
        rs(1.5)  # type: ignore[arg-type]


# Feature: ui, Property 3: Every unit has both sources
@settings(max_examples=16)
@given(st.sampled_from(UNIT_ORDER))
def test_every_unit_has_both_sources(name: str) -> None:
    """**Validates: Requirements 2.3, 2.4**"""
    legacy = legacy_source(name).upper()
    assert f"FUNCTION {name}".upper() in legacy or f"PROCEDURE {name}".upper() in legacy
    py = python_source(name)
    assert py.startswith(f"def {PORT_OF[name]}(")
    assert f"BILLING_PKG.{name}" in py


# Feature: ui, Property 4: Unknown units are rejected by name
@given(st.text().filter(lambda t: t not in UNIT_ORDER))
def test_unknown_units_rejected_by_name(text: str) -> None:
    """**Validates: Requirements 2.6**"""
    for fn in (legacy_source, python_source):
        with pytest.raises(KeyError) as exc:
            fn(text)
        assert text in str(exc.value.args[0])


# Feature: ui, Property 5: The autopsy uses the cache when it has an entry and the static fallback when it has not
@settings(max_examples=30, deadline=None)
@given(st.sets(st.sampled_from(UNIT_ORDER)))
def test_autopsy_cache_fallback(hidden: set[str]) -> None:
    """**Validates: Requirements 4.1, 4.2, 4.3, 4.4**"""
    import shutil
    import tempfile
    from pathlib import Path
    from unittest.mock import patch

    from gravedigger.ui.views import build_autopsy_cards

    golden = Path(__file__).resolve().parents[1] / "golden" / "autopsy"

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("no LLM client may be built")

    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "autopsy"
        shutil.copytree(golden, copy)
        for name in hidden:
            for f in copy.glob(f"{name}-*.json"):
                f.unlink()
        with patch("gravedigger.autopsy.explain.make_client", boom), patch(
            "gravedigger.autopsy.explain.client_from_settings", boom
        ):
            cards = build_autopsy_cards(copy)

    assert tuple(c.unit for c in cards) == tuple(UNIT_ORDER)
    for card in cards:
        assert card.source == ("static" if card.unit in hidden else "cache")


# --- run_hunt (Properties 6 and 7) -------------------------------------------
# A hunt over the full golden file is too slow for a property, so these use the
# first few cases only. The full-file equality lives in tests/test_ui.py.


def _small_cases():
    from gravedigger.prove.golden import load_cases
    from gravedigger.ui import views

    return load_cases(views.repo_root() / "golden" / "cases.json")[:5]


# Feature: ui, Property 6: Hunts equal the library hunt and are repeatable
@settings(max_examples=10, deadline=None)
@given(st.sampled_from(["port", "draft"]))
def test_hunts_equal_library_hunt_and_repeat(kind: str) -> None:
    """**Validates: Requirements 5.1, 5.3, 16.2**"""
    from unittest.mock import patch

    from gravedigger.prove.hunt import hunt
    from gravedigger.resurrected import billing, billing_draft
    from gravedigger.ui import views

    small = _small_cases()
    port = {"port": billing.generate_bill, "draft": billing_draft.generate_bill}[kind]
    views.run_hunt.cache_clear()
    try:
        with patch.object(views, "_golden_cases", lambda: small):
            report = views.run_hunt(kind)
            expected = hunt(port, small)
            assert report.checked == len(small)
            assert report.checked == expected.checked
            assert report.matched == expected.matched
            assert report.ghosts == expected.ghosts
            views.run_hunt.cache_clear()
            assert views.run_hunt(kind) == report
    finally:
        views.run_hunt.cache_clear()


# Feature: ui, Property 7: Unknown hunts are rejected
@given(st.text().filter(lambda t: t not in ("port", "draft")))
def test_unknown_hunts_rejected(text: str) -> None:
    """**Validates: Requirements 5.4**"""
    from gravedigger.ui import views

    with pytest.raises(ValueError):
        views.run_hunt(text)


# --- ghost_table (Properties 8 and 9) -------------------------------------------------
# Small reports are built from generated BillInput values and the real port's bill.
# run_hunt is never called here.

_DELTAS = st.one_of(
    st.sampled_from([Decimal(-1), Decimal(1)]),
    st.integers(-5000, 5000).map(lambda n: Decimal(n).scaleb(-2)),
)
_TARIFFS = st.one_of(st.sampled_from(["A1", "A2"]), st.text(max_size=8))


@st.composite
def _small_inputs(draw):  # type: ignore[no-untyped-def]
    """Cheap BillInput values: two tariffs, small readings, no optional fields."""
    from datetime import datetime

    from gravedigger.resurrected.billing import BillInput

    prev = draw(st.integers(0, 5000))
    return BillInput(
        tariff=draw(st.sampled_from(["A1", "A2"])),
        load_kw=Decimal(draw(st.integers(1, 20))),
        prev_rdg=prev,
        curr_rdg=prev + draw(st.integers(0, 3000)),
        mf=Decimal(1),
        rdg_dt=datetime(2026, 1, 1),
        fpa_rate=None,
        pay_dt=None,
    )


@st.composite
def _ghosts(draw):  # type: ignore[no-untyped-def]
    import dataclasses

    from gravedigger.prove.hunt import Ghost
    from gravedigger.resurrected.billing import generate_bill

    bill_input = draw(_small_inputs())
    bill = generate_bill(bill_input)
    oracle = draw(st.one_of(st.none(), st.just(bill)))
    delta = draw(_DELTAS)
    python = dataclasses.replace(bill, total=bill.total + delta)
    tariff = draw(_TARIFFS)
    return Ghost(
        input=dataclasses.replace(bill_input, tariff=tariff),
        oracle=oracle,
        python=python,
        diffs=(),
    )


@st.composite
def _reports(draw):  # type: ignore[no-untyped-def]
    from gravedigger.prove.hunt import HuntReport

    ghosts = tuple(draw(st.lists(_ghosts(), max_size=8)))
    checked = len(ghosts) + draw(st.integers(0, 5))
    return HuntReport(checked=checked, matched=checked - len(ghosts), ghosts=ghosts)


def _size_key(ghost):  # type: ignore[no-untyped-def]
    bill = ghost.oracle if ghost.oracle is not None else ghost.python
    return (bill.units, bill.total)


# Feature: ui, Property 8: The ghost table is limited, ordered and shaped
@settings(max_examples=100, deadline=None, suppress_health_check=list(HealthCheck))
@given(_reports(), st.integers(0, 40))
def test_ghost_table_limited_ordered_shaped(report, limit: int) -> None:  # type: ignore[no-untyped-def]
    """**Validates: Requirements 6.1, 6.2, 6.3, 6.6, 16.3**"""
    from gravedigger.ui.views import GHOST_COLUMNS, ghost_table

    rows = ghost_table(report, limit)
    assert len(rows) == min(len(report.ghosts), limit)
    for row in rows:
        assert tuple(row.keys()) == GHOST_COLUMNS
        assert all(isinstance(v, str) for v in row.values())
    if not report.ghosts:
        assert rows == []
        assert ghost_table(report) == []
    # Sizes follow the library order, small to large.
    ordered = sorted(report.ghosts, key=_size_key)
    shown = ordered[: len(rows)]
    keys = [_size_key(g) for g in shown]
    assert keys == sorted(keys)
    if rows:
        smallest = report.smallest
        assert smallest is not None
        assert _size_key(smallest) == _size_key(ordered[0])
        first = rows[0]
        assert first == ghost_table(report, 1)[0]
        bill = smallest.oracle if smallest.oracle is not None else smallest.python
        assert first["Units"] == format(bill.units.normalize(), ",f")
    assert ghost_table(report, 0) == []


# Feature: ui, Property 9: Ghost table cells are written for people
@settings(max_examples=100, deadline=None, suppress_health_check=list(HealthCheck))
@given(_reports())
def test_ghost_table_cells_for_people(report) -> None:  # type: ignore[no-untyped-def]
    """**Validates: Requirements 6.4, 6.5, 6.7, 6.8, 6.9**"""
    from gravedigger.ui.views import NO_BILL, ghost_table

    ordered = sorted(report.ghosts, key=_size_key)
    rows = ghost_table(report, len(ordered))
    assert len(rows) == len(ordered)
    labels = {"A1": "A1 (home)", "A2": "A2 (shop)"}
    for ghost, row in zip(ordered, rows):
        assert row["Python total"] == rs(ghost.python.total)
        tariff = ghost.input.tariff
        assert row["Tariff"] == labels.get(tariff, tariff)
        if ghost.oracle is None:
            assert row["Oracle total"] == NO_BILL == "no bill"
            assert row["Difference"] == "n/a"
        else:
            assert row["Oracle total"] == rs(ghost.oracle.total)
            diff = ghost.python.total - ghost.oracle.total
            assert row["Difference"] == rs(diff)
            if abs(diff) == 1:
                assert row["Difference"] in ("Rs 1", "-Rs 1")


# --- explain_ghost (Properties 10, 11 and 12) -----------------------------------------
# Half-rupee ghosts are built directly from cents: six parts plus an energy charge that
# makes the unrounded sum exactly n + 0.50. Oracle rounds the half up (n + 1), the
# Python side rounds it to even (n), and only the total differs.

_JARGON = ("Decimal", "NULL", "None", "quantize", "NO_DATA_FOUND", "OTHERS")


@st.composite
def _half_rupee_ghosts(draw):  # type: ignore[no-untyped-def]
    import dataclasses
    from datetime import date, datetime

    from gravedigger.prove.compare import FieldDiff
    from gravedigger.prove.hunt import Ghost
    from gravedigger.resurrected.billing import Bill, BillInput

    n = draw(st.integers(1000, 500_000).map(lambda k: 2 * k))
    cents = st.integers(0, 100_000).map(lambda c: Decimal(c).scaleb(-2))
    fix, fpa, ed, gst, tv, lps = (draw(cents) for _ in range(6))
    pre = Decimal(n) + Decimal("0.50")
    enrg = pre - (fix + fpa + ed + gst + tv + lps)
    oracle = Bill(
        units=Decimal(100), enrg=enrg, fix=fix, fpa=fpa, ed=ed, gst=gst, tv=tv,
        lps=lps, total=Decimal(n + 1), due_dt=date(2026, 1, 15),
    )
    python = dataclasses.replace(oracle, total=Decimal(n))
    bill_input = BillInput(
        tariff="A1", load_kw=Decimal(1), prev_rdg=0, curr_rdg=100, mf=Decimal(1),
        rdg_dt=datetime(2026, 1, 1), fpa_rate=None, pay_dt=None,
    )
    return Ghost(
        input=bill_input,
        oracle=oracle,
        python=python,
        diffs=(FieldDiff("total", oracle.total, python.total),),
    ), n


# Feature: ui, Property 10: Half-rupee ghosts are explained as a rounding tie
@settings(max_examples=25, deadline=None)
@given(_half_rupee_ghosts())
def test_half_rupee_ghost_explained(case) -> None:  # type: ignore[no-untyped-def]
    """**Validates: Requirements 7.1, 7.2, 7.3**"""
    from gravedigger.ui.views import explain_ghost

    ghost, n = case
    text = explain_ghost(ghost)
    assert rs(Decimal(n + 1)) in text
    assert rs(Decimal(n)) in text
    assert rs(Decimal(n) + Decimal("0.50")) in text
    assert "half" in text
    assert "round()" in text


# Feature: ui, Property 11: A missing Oracle bill is named as such
@settings(max_examples=15, deadline=None, suppress_health_check=list(HealthCheck))
@given(_ghosts())
def test_missing_oracle_bill_explained(ghost) -> None:  # type: ignore[no-untyped-def]
    """**Validates: Requirements 7.4**"""
    import dataclasses

    from gravedigger.ui.views import explain_ghost

    text = explain_ghost(dataclasses.replace(ghost, oracle=None))
    assert "no bill" in text
    assert rs(ghost.python.total) in text


# Feature: ui, Property 12: Every ghost gets plain, deterministic text
@settings(max_examples=20, deadline=None, suppress_health_check=list(HealthCheck))
@given(st.one_of(_ghosts(), _half_rupee_ghosts().map(lambda c: c[0])))
def test_every_ghost_explained_plainly(ghost) -> None:  # type: ignore[no-untyped-def]
    """**Validates: Requirements 7.5, 7.6**"""
    from gravedigger.ui.views import explain_ghost

    text = explain_ghost(ghost)
    assert text.strip()
    assert text == explain_ghost(ghost)
    for word in _JARGON:
        assert word not in text


# Feature: ui, Property 13: The hunt headline states the ghost count
@settings(max_examples=300, deadline=None, suppress_health_check=list(HealthCheck))
@given(_reports())
def test_hunt_headline_states_ghost_count(report) -> None:  # type: ignore[no-untyped-def]
    """**Validates: Requirements 15.2, 15.3**"""
    from gravedigger.ui.views import hunt_headline

    text = hunt_headline(report)
    n = len(report.ghosts)
    assert f"{report.checked:,}" in text
    if n == 0:
        assert "No ghosts" in text
    else:
        assert f"{n} ghost" in text
        assert f"{report.matched:,}" in text
        if n == 1:
            assert "1 ghost found" in text
            assert "ghosts" not in text
        else:
            assert f"{n} ghosts found" in text


_MD_SPECIAL_CHARS = "\\`*_~$[]<>"
_colours = st.from_regex(r"#[0-9a-fA-F]{6}", fullmatch=True)


def _md_unescape(escaped: str) -> str:
    """Undo md_escape: a backslash makes the next character literal."""
    out: list[str] = []
    i = 0
    while i < len(escaped):
        if escaped[i] == "\\":
            i += 1
            out.append(escaped[i])
        else:
            out.append(escaped[i])
        i += 1
    return "".join(out)


# Feature: ui, Property 14: Page text is escaped and pills keep their text
@given(st.text(alphabet=st.one_of(st.sampled_from(_MD_SPECIAL_CHARS), st.characters())))
def test_md_escape_round_trip_and_no_bare_special(text: str) -> None:
    """**Validates: Requirements 9.3, 9.5, 12.3, 13.2**"""
    from gravedigger.ui.views import md_escape

    escaped = md_escape(text)
    assert _md_unescape(escaped) == text
    # Walk the escaped text: every special must be preceded by its escaping backslash.
    i = 0
    while i < len(escaped):
        if escaped[i] == "\\":
            assert i + 1 < len(escaped) and escaped[i + 1] in _MD_SPECIAL_CHARS
            i += 2
        else:
            assert escaped[i] not in _MD_SPECIAL_CHARS
            i += 1


# Feature: ui, Property 14: Page text is escaped and pills keep their text
@given(st.text(), _colours)
def test_pill_html_keeps_text_and_colour(text: str, colour: str) -> None:
    """**Validates: Requirements 9.3, 9.5, 12.3, 13.2**"""
    import html

    from gravedigger.ui.views import pill_html

    out = pill_html(text, colour)
    assert out.count("<span") == 1
    assert out.count("</span>") == 1
    assert out.startswith("<span") and out.endswith("</span>")
    assert colour in out
    inner = out[out.index(">") + 1 : -len("</span>")]
    assert "<" not in inner and ">" not in inner
    assert html.unescape(inner) == text


# Feature: ui, Property 14: Page text is escaped and pills keep their text
@given(st.text().filter(lambda c: re.fullmatch(r"#[0-9a-fA-F]{6}", c) is None))
def test_pill_html_rejects_bad_colours(colour: str) -> None:
    """**Validates: Requirements 9.5**"""
    from gravedigger.ui.views import pill_html

    with pytest.raises(ValueError):
        pill_html("x", colour)


# Feature: ui, Property 14: Page text is escaped and pills keep their text
@given(st.lists(st.integers(1, 2000), min_size=1, max_size=6).map(tuple), st.text())
def test_citation_contains_every_line(lines: tuple[int, ...], text: str) -> None:
    """**Validates: Requirements 12.3, 13.2**"""
    from gravedigger.autopsy.explain import Rule
    from gravedigger.ui.views import citation

    out = citation(Rule(text=text, lines=lines, category="tax"))
    for n in lines:
        assert re.search(rf"(?<!\d){n}(?!\d)", out)


# Feature: ui, Property 13 (examples): 0, 1 and many ghosts
@pytest.mark.parametrize("n_ghosts", [0, 1, 5])
def test_hunt_headline_examples(n_ghosts: int) -> None:
    """**Validates: Requirements 15.2, 15.3**"""
    import dataclasses
    from datetime import datetime

    from gravedigger.prove.hunt import Ghost, HuntReport
    from gravedigger.resurrected.billing import BillInput, generate_bill
    from gravedigger.ui.views import hunt_headline

    bill_input = BillInput(
        tariff="A1", load_kw=Decimal(1), prev_rdg=0, curr_rdg=100, mf=Decimal(1),
        rdg_dt=datetime(2026, 1, 1), fpa_rate=None, pay_dt=None,
    )
    bill = generate_bill(bill_input)
    ghost = Ghost(
        input=bill_input, oracle=bill,
        python=dataclasses.replace(bill, total=bill.total + 1), diffs=(),
    )
    report = HuntReport(checked=1000, matched=1000 - n_ghosts, ghosts=(ghost,) * n_ghosts)
    text = hunt_headline(report)
    if n_ghosts == 0:
        assert text == "No ghosts. All 1,000 bills match Oracle to the paisa."
    elif n_ghosts == 1:
        assert text.startswith("1 ghost found.") and "ghosts" not in text
    else:
        assert text.startswith("5 ghosts found.") and "995 of 1,000" in text
