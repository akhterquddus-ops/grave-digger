-- ==========================================================================
-- SYNTHETIC LEGACY CODE - written in November 2026 for the Grave Digger
-- project (Kiroween 2026). It imitates 2000s-era style on purpose. All names,
-- rates, rules and dated comments are fictional and resemble no real utility.
-- ==========================================================================
-- BILLING_PKG spec
-- 02-MAR-2004 SKM: created
-- 17-AUG-2008 RKH: added p_taxes, f_lps

CREATE OR REPLACE PACKAGE billing_pkg AS

  -- debug flag, 1 = print with DBMS_OUTPUT (SKM: leave 0 in prod!!)
  g_dbg NUMBER := 0;

  -- units consumed from two readings of a 5 digit meter
  FUNCTION f_units    (p_prev NUMBER, p_curr NUMBER, p_mf NUMBER) RETURN NUMBER;

  -- energy charge
  FUNCTION f_enrg_chg (p_tariff VARCHAR2, p_units NUMBER) RETURN NUMBER;

  -- fixed charge
  FUNCTION f_fix_chg  (p_tariff VARCHAR2, p_load_kw NUMBER, p_enrg NUMBER) RETURN NUMBER;

  -- fuel price adjustment
  FUNCTION f_fpa      (p_units NUMBER, p_bill_mon VARCHAR2) RETURN NUMBER;

  -- electricity duty + GST (was function f_taxes, OUT params so now a procedure)
  PROCEDURE p_taxes   (p_enrg NUMBER, p_fix NUMBER, p_fpa NUMBER,
                       o_ed OUT NUMBER, o_gst OUT NUMBER);

  -- due date
  FUNCTION f_due_dt   (p_rdg_dt DATE) RETURN DATE;

  -- late payment surcharge
  FUNCTION f_lps      (p_enrg NUMBER, p_due_dt DATE, p_pay_dt DATE) RETURN NUMBER;

  -- generate one bill into BILL_HDR
  PROCEDURE p_gen_bill (p_cust_no NUMBER, p_bill_mon VARCHAR2);

END billing_pkg;
/
