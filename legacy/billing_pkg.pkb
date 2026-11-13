-- ==========================================================================
-- SYNTHETIC LEGACY CODE - written in November 2026 for the Grave Digger
-- project (Kiroween 2026). It imitates 2000s-era style on purpose. All names,
-- rates, rules and dated comments are fictional and resemble no real utility.
-- ==========================================================================
-- BILLING_PKG body
-- 02-MAR-2004 SKM: created
-- 12-MAR-2006 RKH: slab 3 was 15.50
-- 09-SEP-2006 RKH: A2 flat rate was 21, now 25
-- 17-AUG-2008 RKH: added p_taxes, f_lps
-- 30-JUN-2009 MPV: TV fee added to bill

CREATE OR REPLACE PACKAGE BODY billing_pkg AS

  ---------------------------------------------------------------------------
  -- f_units : units from readings, handles 5 digit meter rollover
  ---------------------------------------------------------------------------
  FUNCTION f_units (p_prev NUMBER, p_curr NUMBER, p_mf NUMBER) RETURN NUMBER IS
    n_unt NUMBER;
  BEGIN
    IF p_curr < p_prev THEN
      -- meter went past 99999 and came back to 0
      n_unt := (99999 - p_prev + p_curr + 1) * p_mf;
    ELSE
      n_unt := (p_curr - p_prev) * p_mf;
    END IF;
    IF g_dbg = 1 THEN
      DBMS_OUTPUT.PUT_LINE('f_units n_unt=' || n_unt);
    END IF;
    RETURN n_unt;
  END f_units;

  ---------------------------------------------------------------------------
  -- f_enrg_chg : energy charge
  --   A1 telescopic 1-100 @10, 101-200 @13, 201-300 @16, above 300 ALL @22
  --   A2 flat @25
  ---------------------------------------------------------------------------
  FUNCTION f_enrg_chg (p_tariff VARCHAR2, p_units NUMBER) RETURN NUMBER IS
    v_enrg_chg NUMBER := 0;
  BEGIN
    IF p_tariff = 'A1' THEN
      IF p_units > 300 THEN
        -- RKH 2006: whole consumption at top rate once past 300
        v_enrg_chg := p_units * 22;
      ELSE
        IF p_units > 200 THEN
          v_enrg_chg := 100 * 10 + 100 * 13 + (p_units - 200) * 16;
          -- v_enrg_chg := 100 * 10 + 100 * 13 + (p_units - 200) * 15.50;  -- 12-MAR-2006 RKH: slab 3 was 15.50
        ELSIF p_units > 100 THEN
          v_enrg_chg := 100 * 10 + (p_units - 100) * 13;
        ELSE
          v_enrg_chg := p_units * 10;
        END IF;
      END IF;
    ELSIF p_tariff = 'A2' THEN
      v_enrg_chg := p_units * 25;
      -- v_enrg_chg := p_units * 21;  -- 09-SEP-2006 RKH: old A2 rate
    ELSE
      v_enrg_chg := 0;
    END IF;
    IF g_dbg = 1 THEN
      DBMS_OUTPUT.PUT_LINE('f_enrg_chg ' || p_tariff || ' ' || p_units || ' = ' || v_enrg_chg);
    END IF;
    RETURN ROUND(v_enrg_chg, 2);
  END f_enrg_chg;

  ---------------------------------------------------------------------------
  -- f_fix_chg : fixed charge
  --   A2 = 400 per sanctioned kW
  --   A1 = 0, but minimum bill Rs 75 : top up if energy charge below 75
  ---------------------------------------------------------------------------
  FUNCTION f_fix_chg (p_tariff VARCHAR2, p_load_kw NUMBER, p_enrg NUMBER) RETURN NUMBER IS
    v_fix NUMBER := 0;
  BEGIN
    IF p_tariff = 'A2' THEN
      v_fix := 400 * p_load_kw;
    ELSIF p_tariff = 'A1' THEN
      IF p_enrg < 75 THEN
        v_fix := 75 - p_enrg;
      ELSE
        v_fix := 0;
      END IF;
    END IF;
    IF g_dbg = 1 THEN
      DBMS_OUTPUT.PUT_LINE('f_fix_chg = ' || v_fix);
    END IF;
    RETURN v_fix;
  END f_fix_chg;

  ---------------------------------------------------------------------------
  -- f_fpa : fuel price adjustment = units * monthly rate, 0 if no rate loaded
  ---------------------------------------------------------------------------
  FUNCTION f_fpa (p_units NUMBER, p_bill_mon VARCHAR2) RETURN NUMBER IS
    n_rt NUMBER;
  BEGIN
    SELECT rate_per_kwh INTO n_rt FROM FPA_RT WHERE bill_mon = p_bill_mon;
    RETURN ROUND(p_units * n_rt, 2);
  EXCEPTION
    WHEN NO_DATA_FOUND THEN
      -- rate not loaded yet for the month, bill without FPA (SKM 2005)
      RETURN 0;
  END f_fpa;

  ---------------------------------------------------------------------------
  -- p_taxes : (legacy name f_taxes) ED 1.5% of energy, GST 17% on everything
  --           including the ED  (tax on tax)
  ---------------------------------------------------------------------------
  PROCEDURE p_taxes (p_enrg NUMBER, p_fix NUMBER, p_fpa NUMBER,
                     o_ed OUT NUMBER, o_gst OUT NUMBER) IS
  BEGIN
    o_ed  := ROUND(p_enrg * 0.015, 2);
    o_gst := ROUND((p_enrg + p_fix + p_fpa + o_ed) * 0.17, 2);
  END p_taxes;

  ---------------------------------------------------------------------------
  -- f_due_dt : reading date + 14 days, Sunday moves to Monday
  ---------------------------------------------------------------------------
  FUNCTION f_due_dt (p_rdg_dt DATE) RETURN DATE IS
    d_due DATE;
  BEGIN
    d_due := TRUNC(p_rdg_dt) + 14;
    IF TO_CHAR(d_due, 'DY', 'NLS_DATE_LANGUAGE=ENGLISH') = 'SUN' THEN
      d_due := d_due + 1;
    END IF;
    RETURN d_due;
  END f_due_dt;

  ---------------------------------------------------------------------------
  -- f_lps : late payment surcharge, 10% of energy charge if paid after due
  ---------------------------------------------------------------------------
  FUNCTION f_lps (p_enrg NUMBER, p_due_dt DATE, p_pay_dt DATE) RETURN NUMBER IS
  BEGIN
    IF p_pay_dt IS NULL THEN
      RETURN 0;
    END IF;
    IF p_pay_dt > p_due_dt THEN
      RETURN ROUND(p_enrg * 0.10, 2);
    ELSE
      RETURN 0;
    END IF;
  END f_lps;

  ---------------------------------------------------------------------------
  -- p_gen_bill : build one bill and insert into BILL_HDR
  ---------------------------------------------------------------------------
  PROCEDURE p_gen_bill (p_cust_no NUMBER, p_bill_mon VARCHAR2) IS
    n_unt      NUMBER;
    v_enrg_chg NUMBER;
    v_fix      NUMBER;
    v_fpa      NUMBER;
    v_ed       NUMBER;
    v_gst      NUMBER;
    v_tv       NUMBER;
    v_lps      NUMBER;
    n_tot      NUMBER;
    d_due      DATE;
    d_pay      DATE;
    n_prev     NUMBER;
    n_curr     NUMBER;
    d_rdg      DATE;
  BEGIN
    FOR c IN (SELECT cust_no, tariff, load_kw, mf FROM CUST_MST WHERE cust_no = p_cust_no) LOOP

      -- no reading row => NO_DATA_FOUND => caught by WHEN OTHERS below
      SELECT prev_rdg, curr_rdg, rdg_dt
        INTO n_prev, n_curr, d_rdg
        FROM MTR_RDG
       WHERE cust_no = c.cust_no AND bill_mon = p_bill_mon;

      n_unt      := f_units(n_prev, n_curr, c.mf);
      v_enrg_chg := f_enrg_chg(c.tariff, n_unt);
      v_fix      := f_fix_chg(c.tariff, c.load_kw, v_enrg_chg);
      v_fpa      := f_fpa(n_unt, p_bill_mon);
      p_taxes(v_enrg_chg, v_fix, v_fpa, v_ed, v_gst);
      d_due      := f_due_dt(d_rdg);

      BEGIN
        SELECT pay_dt INTO d_pay FROM PYMT
         WHERE cust_no = c.cust_no AND bill_mon = p_bill_mon;
      EXCEPTION
        WHEN NO_DATA_FOUND THEN
          d_pay := NULL;
      END;
      v_lps := f_lps(v_enrg_chg, d_due, d_pay);

      -- TV fee is not taxed
      IF c.tariff = 'A1' THEN
        v_tv := 35;
      ELSE
        v_tv := 60;
      END IF;

      n_tot := ROUND(v_enrg_chg + v_fix + v_fpa + v_ed + v_gst + v_tv + v_lps, 0);

      INSERT INTO BILL_HDR (cust_no, bill_mon, units, enrg_chg, fix_chg, fpa, ed, gst,
                            tv_fee, lps, total, due_dt, gen_dt)
      VALUES (c.cust_no, p_bill_mon, n_unt, v_enrg_chg, v_fix, v_fpa, v_ed, v_gst,
              v_tv, v_lps, n_tot, d_due, SYSDATE);

      IF g_dbg = 1 THEN
        DBMS_OUTPUT.PUT_LINE('bill ' || c.cust_no || ' ' || p_bill_mon || ' total=' || n_tot);
      END IF;
    END LOOP;
  EXCEPTION
    WHEN OTHERS THEN
      NULL;  -- SKM: batch must never stop
  END p_gen_bill;

END billing_pkg;
/
