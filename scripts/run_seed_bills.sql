SET LINESIZE 200 PAGESIZE 50 FEEDBACK OFF
SELECT object_name, object_type, status FROM user_objects WHERE object_name = 'BILLING_PKG';
SELECT name, line, text FROM user_errors WHERE name = 'BILLING_PKG';
DELETE FROM bill_hdr;
BEGIN
  FOR c IN (SELECT cust_no FROM cust_mst ORDER BY cust_no) LOOP
    billing_pkg.p_gen_bill(c.cust_no, CASE c.cust_no WHEN 1004 THEN '202402' ELSE '202401' END);
  END LOOP;
  COMMIT;
END;
/
COLUMN due FORMAT A11
SELECT cust_no, units, enrg_chg, fix_chg, fpa, ed, gst, tv_fee, lps, total,
       TO_CHAR(due_dt, 'DD-MON-YYYY', 'NLS_DATE_LANGUAGE=ENGLISH') due
  FROM bill_hdr ORDER BY cust_no;
EXIT