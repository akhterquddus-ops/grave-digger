-- ==========================================================================
-- SYNTHETIC LEGACY CODE - written in November 2026 for the Grave Digger
-- project (Kiroween 2026). It imitates 2000s-era style on purpose. All names,
-- rates, rules and dated comments are fictional and resemble no real utility.
-- ==========================================================================
-- schema.sql : tables + seed data for BILLING_PKG
-- 14-FEB-2004 SKM: first cut
-- 03-NOV-2007 RKH: added PYMT table for late payment surcharge
-- 21-JUN-2009 RKH: BILL_HDR now has tv_fee column

-- drop old tables (ignore errors on first run)
BEGIN
  FOR r IN (SELECT 'BILL_HDR' t FROM dual UNION ALL SELECT 'PYMT' FROM dual
            UNION ALL SELECT 'FPA_RT' FROM dual UNION ALL SELECT 'MTR_RDG' FROM dual
            UNION ALL SELECT 'CUST_MST' FROM dual) LOOP
    BEGIN
      EXECUTE IMMEDIATE 'DROP TABLE ' || r.t || ' PURGE';
    EXCEPTION
      WHEN OTHERS THEN NULL;
    END;
  END LOOP;
END;
/

CREATE TABLE CUST_MST (
  cust_no   NUMBER(6)     NOT NULL,
  cust_nm   VARCHAR2(40)  NOT NULL,
  tariff    VARCHAR2(2)   NOT NULL,   -- A1 = household, A2 = shop
  load_kw   NUMBER(6,2)   NOT NULL,   -- sanctioned load in kW
  mf        NUMBER(6,2)   DEFAULT 1 NOT NULL,  -- meter multiplying factor
  CONSTRAINT pk_cust_mst PRIMARY KEY (cust_no)
);

CREATE TABLE MTR_RDG (
  cust_no   NUMBER(6)     NOT NULL,
  bill_mon  VARCHAR2(6)   NOT NULL,   -- YYYYMM
  prev_rdg  NUMBER(5)     NOT NULL,   -- 5 digit meter
  curr_rdg  NUMBER(5)     NOT NULL,
  rdg_dt    DATE          NOT NULL,
  CONSTRAINT pk_mtr_rdg PRIMARY KEY (cust_no, bill_mon)
);

CREATE TABLE FPA_RT (
  bill_mon      VARCHAR2(6)  NOT NULL,
  rate_per_kwh  NUMBER(8,4)  NOT NULL,
  CONSTRAINT pk_fpa_rt PRIMARY KEY (bill_mon)
);

CREATE TABLE PYMT (
  cust_no   NUMBER(6)     NOT NULL,
  bill_mon  VARCHAR2(6)   NOT NULL,
  pay_dt    DATE          NOT NULL,   -- keeps the time part, cashier counter stamps it
  pay_amt   NUMBER(12,2),
  CONSTRAINT pk_pymt PRIMARY KEY (cust_no, bill_mon)
);

CREATE TABLE BILL_HDR (
  cust_no   NUMBER(6)     NOT NULL,
  bill_mon  VARCHAR2(6)   NOT NULL,
  units     NUMBER(12,2),
  enrg_chg  NUMBER(12,2),
  fix_chg   NUMBER(12,2),
  fpa       NUMBER(12,2),
  ed        NUMBER(12,2),
  gst       NUMBER(12,2),
  tv_fee    NUMBER(12,2),
  lps       NUMBER(12,2),
  total     NUMBER(12),
  due_dt    DATE,
  gen_dt    DATE,
  CONSTRAINT pk_bill_hdr PRIMARY KEY (cust_no, bill_mon)
);

-- --------------------------------------------------------------------------
-- seed data : 6 customers, each one exercises a rule
-- --------------------------------------------------------------------------
INSERT INTO CUST_MST VALUES (1001, 'Test Cust One',   'A1',  2.00, 1);
INSERT INTO CUST_MST VALUES (1002, 'Test Cust Two',   'A1',  3.00, 1);
INSERT INTO CUST_MST VALUES (1003, 'Test Cust Three', 'A1',  5.00, 2);
INSERT INTO CUST_MST VALUES (1004, 'Test Cust Four',  'A1',  4.00, 1);
INSERT INTO CUST_MST VALUES (1005, 'Test Shop Five',  'A2',  7.50, 1);
INSERT INTO CUST_MST VALUES (1006, 'Test Shop Six',   'A2',  3.00, 1);

-- FPA rate only for Jan 2024; Feb 2024 is missing on purpose (NO_DATA_FOUND)
INSERT INTO FPA_RT VALUES ('202401', 0.35);
INSERT INTO FPA_RT VALUES ('202312', 0.5);

-- 1001: 5 units -> energy 50.00 < 75, minimum charge top-up; no payment (NULL pay_dt)
INSERT INTO MTR_RDG VALUES (1001, '202401', 1000, 1005, TO_DATE('10-JAN-2024','DD-MON-YYYY','NLS_DATE_LANGUAGE=ENGLISH'));

-- 1002: 150 units -> telescopic slabs 1 and 2; paid on time
INSERT INTO MTR_RDG VALUES (1002, '202401', 2000, 2150, TO_DATE('10-JAN-2024','DD-MON-YYYY','NLS_DATE_LANGUAGE=ENGLISH'));
INSERT INTO PYMT VALUES (1002, '202401', TO_DATE('20-JAN-2024 11:30','DD-MON-YYYY HH24:MI','NLS_DATE_LANGUAGE=ENGLISH'), 1500);

-- 1003: meter rolled over 99900 -> 50, mf 2 => 300 units (slab 3 edge, no cliff);
--       reading on Sunday 07-JAN-2024, due 21-JAN is Sunday -> shifted to 22-JAN;
--       paid 22-JAN at 10:00, which is AFTER midnight due_dt => counted late
INSERT INTO MTR_RDG VALUES (1003, '202401', 99900, 50, TO_DATE('07-JAN-2024','DD-MON-YYYY','NLS_DATE_LANGUAGE=ENGLISH'));
INSERT INTO PYMT VALUES (1003, '202401', TO_DATE('22-JAN-2024 10:00','DD-MON-YYYY HH24:MI','NLS_DATE_LANGUAGE=ENGLISH'), 4000);

-- 1004: 301 units -> cliff, ALL units at 22; FPA month 202402 missing -> 0;
--       paid clearly late
INSERT INTO MTR_RDG VALUES (1004, '202402', 5000, 5301, TO_DATE('05-FEB-2024','DD-MON-YYYY','NLS_DATE_LANGUAGE=ENGLISH'));
INSERT INTO PYMT VALUES (1004, '202402', TO_DATE('25-FEB-2024 09:15','DD-MON-YYYY HH24:MI','NLS_DATE_LANGUAGE=ENGLISH'), 9000);

-- 1005: A2 shop, flat 25/kWh, fixed 400 per kW, TV fee 60; paid exactly at midnight of due date
INSERT INTO MTR_RDG VALUES (1005, '202401', 100, 400, TO_DATE('10-JAN-2024','DD-MON-YYYY','NLS_DATE_LANGUAGE=ENGLISH'));
INSERT INTO PYMT VALUES (1005, '202401', TO_DATE('24-JAN-2024','DD-MON-YYYY','NLS_DATE_LANGUAGE=ENGLISH'), 12000);

-- 1006: A2 shop with NO meter reading for the month -> p_gen_bill fails silently,
--       no BILL_HDR row (WHEN OTHERS THEN NULL)

COMMIT;
