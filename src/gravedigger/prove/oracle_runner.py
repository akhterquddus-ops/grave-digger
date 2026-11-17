"""Bill one probe customer through the real legacy procedure in Oracle."""

from __future__ import annotations

import decimal

import oracledb

from gravedigger.resurrected.billing import Bill, BillInput

PROBE_CUST_NO = 900001
PROBE_BILL_MON = "209912"

_INSERT_CUST = (
    "INSERT INTO CUST_MST (cust_no, cust_nm, tariff, load_kw, mf) "
    "VALUES (:c, 'probe', :t, :l, :m)"
)
_INSERT_RDG = (
    "INSERT INTO MTR_RDG (cust_no, bill_mon, prev_rdg, curr_rdg, rdg_dt) "
    "VALUES (:c, :bm, :p, :cu, :d)"
)
_INSERT_FPA = "INSERT INTO FPA_RT (bill_mon, rate_per_kwh) VALUES (:bm, :r)"
_INSERT_PYMT = "INSERT INTO PYMT (cust_no, bill_mon, pay_dt) VALUES (:c, :bm, :d)"
_SELECT_BILL = (
    "SELECT units, enrg_chg, fix_chg, fpa, ed, gst, tv_fee, lps, total, due_dt "
    "FROM BILL_HDR WHERE cust_no = :c AND bill_mon = :bm"
)


def _decimal_handler(cursor: oracledb.Cursor, metadata: oracledb.FetchInfo):
    """Fetch every NUMBER column as decimal.Decimal (per cursor, no global state)."""
    if metadata.type_code is oracledb.DB_TYPE_NUMBER:
        return cursor.var(decimal.Decimal, arraysize=cursor.arraysize)
    return None


def run_oracle(conn: oracledb.Connection, b: BillInput) -> Bill | None:
    """Bill one probe customer with BILLING_PKG.p_gen_bill (pkb lines 146-207).

    Inserts the customer, reading and optional FPA rate and payment, calls the
    legacy procedure, reads the BILL_HDR row, and always rolls back. Oracle
    errors propagate unchanged. Returns None when the legacy code wrote no row
    (its WHEN OTHERS THEN NULL swallowed an error).
    """
    try:
        with conn.cursor() as cur:
            cur.outputtypehandler = _decimal_handler
            cur.execute(_INSERT_CUST, c=PROBE_CUST_NO, t=b.tariff, l=b.load_kw, m=b.mf)
            cur.execute(
                _INSERT_RDG,
                c=PROBE_CUST_NO,
                bm=PROBE_BILL_MON,
                p=b.prev_rdg,
                cu=b.curr_rdg,
                d=b.rdg_dt,
            )
            if b.fpa_rate is not None:
                cur.execute(_INSERT_FPA, bm=PROBE_BILL_MON, r=b.fpa_rate)
            if b.pay_dt is not None:
                cur.execute(_INSERT_PYMT, c=PROBE_CUST_NO, bm=PROBE_BILL_MON, d=b.pay_dt)
            cur.callproc("BILLING_PKG.P_GEN_BILL", [PROBE_CUST_NO, PROBE_BILL_MON])
            cur.execute(_SELECT_BILL, c=PROBE_CUST_NO, bm=PROBE_BILL_MON)
            rows = cur.fetchall()
        if not rows:
            return None
        u, enrg, fix, fpa, ed, gst, tv, lps, total, due = rows[0]
        return Bill(u, enrg, fix, fpa, ed, gst, tv, lps, total, due.date())
    finally:
        conn.rollback()
