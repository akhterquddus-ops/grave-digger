# Requirements Document

## Introduction

Exhume and the Autopsy scanner are the first two stages of Grave Digger. Exhume loads a PL/SQL package (spec text and body text) and splits the body into units. The Autopsy scanner reads one unit and reports plain facts about it: numeric constants, string literals, tables touched, calls to sibling units, branch counts, handled exceptions and swallowed errors. Every fact carries the line of `legacy/billing_pkg.pkb` it came from, so later autopsy rules can cite real code. Commented-out code and text inside string literals never count as rules.

The acceptance tests are in `tests/test_autopsy_scanner.py` and are not modified by this feature. All line numbers below are 1-based lines of `legacy/billing_pkg.pkb`, header comments included. Oracle's stored source starts at the CREATE line, so a database line equals the file line minus 12. Database line numbers are not used anywhere in this spec.

## Glossary

- **Exhumer**: The component in `gravedigger.exhume` that provides `load_package`.
- **Scanner**: The component in `gravedigger.autopsy.scanner` that provides `scan`.
- **Tokenizer**: The shared routine that masks comments and string literals while keeping every line number.
- **Package**: Frozen dataclass with `name`, `globals` and `units`.
- **Unit**: Frozen dataclass with `name`, `kind`, `params`, `return_type`, `start_line`, `end_line` and `source`. A Unit also knows the unit names and global names of its Package.
- **Param**: Frozen dataclass with `name`, `mode` and `datatype`.
- **Global**: Frozen dataclass with `name`, a package-level variable declared in the package spec.
- **Constant**: Frozen dataclass with `value` (Decimal), `line` and column position.
- **Facts**: Frozen dataclass with `constants`, `string_literals`, `tables_read`, `tables_written`, `calls`, `branches`, `exceptions_handled`, `swallows_errors` and `globals_used`.
- **Masked_Source**: Unit source in which comment text and string-literal text are replaced by spaces, with all newline characters preserved.
- **Live_Code**: The part of a unit that remains visible in Masked_Source.
- **Sibling_Unit**: Another unit of the same Package.
- **Whole_Word**: A match of a name that is not directly preceded or followed by a letter, a digit, `_`, `$` or `#`.
- **Swallowed_Error**: An exception handler for `OTHERS` whose body, ignoring whitespace and comments, consists only of `NULL;`.
- **Exception_Section**: A handler section inside a unit. It starts at an `EXCEPTION` keyword that belongs to the unit body or to a nested `BEGIN ... END` block of that unit, and ends at the `END` that closes the block holding that keyword. A unit can have several (for example `p_gen_bill` has one nested and one outer).

## Requirements

### Requirement 1: Package identity and globals

**User Story:** As a migration engineer, I want the package name and its global variables, so that I know the state the units share.

#### Acceptance Criteria

1. WHEN spec text and body text are passed to `load_package`, THE Exhumer SHALL return a Package whose `name` is the name given in `CREATE OR REPLACE PACKAGE`, converted to lower case (`billing_pkg` for the legacy file).
2. WHEN the package spec declares a global variable, THE Exhumer SHALL list that variable in `Package.globals` as a Global with a lower-case name (`g_dbg` for the legacy file).
3. WHEN the package spec declares several global variables, THE Exhumer SHALL list them in `Package.globals` in declared order.
4. IF the package spec declares no global variable, THEN THE Exhumer SHALL return a Package whose `globals` is empty.
5. THE Exhumer SHALL return Package, Unit, Param and Global values as frozen dataclasses.
6. WHEN code assigns to a field of a Package, Unit, Param or Global value, THE Exhumer value SHALL raise `dataclasses.FrozenInstanceError`.
7. IF the spec text contains no `CREATE OR REPLACE PACKAGE` statement, THEN THE Exhumer SHALL raise `ValueError`.

### Requirement 2: Unit discovery and order

**User Story:** As a migration engineer, I want every function and procedure found in the order written, so that one spec can be created per unit.

#### Acceptance Criteria

1. WHEN a package body is loaded, THE Exhumer SHALL return one Unit per top-level function or procedure, in body order.
2. WHEN the legacy body is loaded, THE Exhumer SHALL return exactly 8 units, with no additional units, named `f_units`, `f_enrg_chg`, `f_fix_chg`, `f_fpa`, `p_taxes`, `f_due_dt`, `f_lps`, `p_gen_bill` in that order.
3. THE Exhumer SHALL set `Unit.kind` to `function` or `procedure` according to the declaring keyword.
4. WHEN a unit is a function, THE Exhumer SHALL set `Unit.return_type` to the declared return type.
5. WHEN a unit is a procedure, THE Exhumer SHALL set `Unit.return_type` to None.
6. WHEN the legacy body is loaded, THE Exhumer SHALL set `Unit.return_type` to `NUMBER` for `f_units` and to `DATE` for `f_due_dt`.
7. WHEN a function or procedure is declared inside another unit, THE Exhumer SHALL omit that nested unit from the units list.
8. WHEN the text `FUNCTION <name>` or `PROCEDURE <name>` appears only in a comment or a string literal, THE Exhumer SHALL omit it from the units list.
9. IF a package body contains no function or procedure, THEN THE Exhumer SHALL return a Package whose `units` is an empty tuple and SHALL raise no error.
10. THE Exhumer SHALL match the keywords `FUNCTION` and `PROCEDURE` case-insensitively and SHALL return each unit name in lower case.

### Requirement 3: Unit line ranges and source

**User Story:** As an auditor, I want exact line ranges, so that every ported function can cite the legacy lines it replaces.

#### Acceptance Criteria

1. THE Exhumer SHALL number lines starting at 1 for the first line of the body text.
2. THE Exhumer SHALL set `start_line` to the line of the unit's `FUNCTION` or `PROCEDURE` keyword and `end_line` to the line of its closing `END <name>;`.
3. WHEN the legacy body is loaded, THE Exhumer SHALL report these inclusive ranges: f_units 18-31, f_enrg_chg 38-65, f_fix_chg 72-88, f_fpa 93-102, p_taxes 108-113, f_due_dt 118-126, f_lps 131-141, p_gen_bill 146-207.
4. THE Exhumer SHALL set `Unit.source` to the lines of the body text from `start_line` to `end_line` inclusive, identical to the file text of those lines, so that the source starts with the unit declaration and ends with `END <name>;`.
5. THE Exhumer SHALL keep the comment banner lines above a unit outside that unit's range and outside `Unit.source`.
6. IF a unit has no closing `END <name>;`, THEN THE Exhumer SHALL raise an error that names the unit and SHALL return no partial list of units.

### Requirement 4: Parameters

**User Story:** As a migration engineer, I want each unit's parameters with direction and type, so that Python signatures match the legacy ones.

#### Acceptance Criteria

1. THE Exhumer SHALL list the parameters of each Unit in declared order as Param values.
2. IF a unit declares no parameters, THEN THE Exhumer SHALL return an empty `params` for that unit.
3. WHEN a parameter has no mode keyword, THE Exhumer SHALL set `Param.mode` to `IN`.
4. WHEN a parameter is declared `OUT`, THE Exhumer SHALL set `Param.mode` to `OUT`.
5. WHEN a parameter is declared `IN OUT`, THE Exhumer SHALL set `Param.mode` to `IN OUT`.
6. WHEN the legacy body is loaded, THE Exhumer SHALL return for `f_units` the parameter names `p_prev`, `p_curr`, `p_mf`, for `p_taxes` the modes `IN, IN, IN, OUT, OUT`, and for `f_lps` the datatypes `NUMBER, DATE, DATE`.
7. WHEN a parameter list spans several lines or uses arbitrary spacing between tokens, THE Exhumer SHALL return the same Param values as for the equivalent single-line list.
8. IF a parameter list cannot be parsed, THEN THE Exhumer SHALL raise an error that names the unit.

### Requirement 5: Comment and string masking

**User Story:** As an auditor, I want commented-out code ignored, so that retired rates such as 15.50 and 21 never appear as rules.

#### Acceptance Criteria

1. THE Tokenizer SHALL replace each character of `--` line comments and `/* */` block comments with a space, except newline characters.
2. THE Tokenizer SHALL replace each character of the text of single-quoted string literals with a space, except newline characters, treating a doubled quote `''` as part of the literal.
3. THE Tokenizer SHALL keep every newline character, including `\r`, at its original position.
4. THE Tokenizer SHALL return text with the same number of characters and the same number of lines as its input.
5. WHEN the characters `--` or `/*` appear inside a string literal, THE Tokenizer SHALL treat them as string text.
6. WHEN a quote character appears inside a comment, THE Tokenizer SHALL treat it as comment text.
7. IF a block comment or a string literal is not closed, THEN THE Tokenizer SHALL mask the text to the end of the input and SHALL raise no error.
8. FOR ALL generated PL/SQL snippets, masking SHALL preserve the character count and the line count and SHALL leave no `--` comment text visible (invariant property), and the property test SHALL run at least 200 examples under the `dev` Hypothesis profile.

### Requirement 6: Numeric constants

**User Story:** As a migration engineer, I want every live numeric literal with its line, so that magic numbers are cited exactly.

#### Acceptance Criteria

1. WHEN Facts are scanned for a unit, THE Scanner SHALL return one Constant for each occurrence of a numeric literal in Live_Code, with its `Decimal` value and the file line number, ordered by line and then by column.
2. THE Scanner SHALL construct each Constant value from the literal's text, so that `0.10` stays `Decimal("0.10")` with two decimals and no float is used.
3. WHEN a numeric literal appears only in a comment or a string literal, THE Scanner SHALL omit it from `constants`.
4. IF a unit has no numeric literal in Live_Code, THEN THE Scanner SHALL return an empty `constants` and SHALL raise no error.
5. WHEN scanning `f_units`, THE Scanner SHALL report the constant 99999 on line 23 only.
6. WHEN scanning `f_enrg_chg`, THE Scanner SHALL report the values 300, 22, 200, 100, 10, 13, 16 and 25, with 22 on line 44 only, and SHALL omit 15.50 and 21.
7. WHEN scanning `p_taxes`, `f_fix_chg`, `f_lps`, `f_due_dt` and `p_gen_bill`, THE Scanner SHALL report 0.015 and 0.17; 400 and 75; 0.10 (on line 137); 14; and 35 and 60 respectively.
8. THE Scanner SHALL omit digits that are part of an identifier (for example the `1` in `A1` inside a string, or in `v_x1`).

### Requirement 7: String literals

**User Story:** As a migration engineer, I want literal strings such as tariff codes, so that I know which values drive branches.

#### Acceptance Criteria

1. WHEN Facts are scanned for a unit, THE Scanner SHALL return the contents of every string literal in Live_Code as a set of strings, without the surrounding quotes.
2. THE Scanner SHALL include the empty literal `''` in `string_literals` as the empty string.
3. IF a unit has no string literal, THEN THE Scanner SHALL return an empty `string_literals`.
4. WHEN the same literal text occurs several times in a unit, THE Scanner SHALL include that text in `string_literals` once.
5. WHEN scanning `f_enrg_chg`, THE Scanner SHALL include `A1` and `A2`.
6. WHEN scanning `f_due_dt`, THE Scanner SHALL include `SUN`.
7. WHEN a string literal contains `--`, THE Scanner SHALL return the full literal text (`rate 99 -- not a comment`) and SHALL omit the 99 inside it from `constants`.
8. WHEN a string literal contains a doubled quote `''`, THE Scanner SHALL return it as one quote character.

### Requirement 8: Tables read and written

**User Story:** As a migration engineer, I want to know which tables each unit reads and writes, so that the dependency graph is accurate.

#### Acceptance Criteria

1. WHEN Live_Code contains `FROM <table>` or `JOIN <table>`, THE Scanner SHALL add the upper-case table name to `tables_read`.
2. WHEN Live_Code contains `INSERT INTO`, `UPDATE` or `DELETE FROM` followed by a table, THE Scanner SHALL add the upper-case table name to `tables_written`.
3. WHEN `UPDATE <table>` appears in Live_Code, THE Scanner SHALL add that table to `tables_written`.
4. WHEN whitespace or newlines separate a keyword from its table name, THE Scanner SHALL match the table in the same way as when one space separates them.
5. WHEN a table name carries a schema prefix (`<schema>.<table>`), THE Scanner SHALL record the table name without the schema prefix.
6. WHEN `INSERT INTO <table>` appears, THE Scanner SHALL omit that table from `tables_read`.
7. WHEN the table text occurs only in a comment or a string literal, THE Scanner SHALL omit it from both sets.
8. THE Scanner SHALL list each table once per set.
9. WHEN scanning the legacy units, THE Scanner SHALL return these table sets:
   - `f_fpa`: reads `FPA_RT`; writes nothing.
   - `p_gen_bill`: reads `CUST_MST`, `MTR_RDG` and `PYMT`; writes `BILL_HDR`.
   - `f_units`: reads and writes no tables.

### Requirement 9: Calls to sibling units

**User Story:** As a migration engineer, I want each unit's calls to other units, so that the dependency graph can be drawn.

#### Acceptance Criteria

1. WHEN Live_Code uses the name of a Sibling_Unit as a Whole_Word, THE Scanner SHALL add that lower-case name to `calls`, matching case-insensitively.
2. THE Scanner SHALL list each called name once.
3. THE Scanner SHALL omit the scanned unit's own name from `calls`, including when the unit calls itself recursively.
4. WHEN a Sibling_Unit name appears only in a comment or a string literal, THE Scanner SHALL omit it from `calls`.
5. WHEN a Sibling_Unit name appears only as a substring of a longer identifier, THE Scanner SHALL omit it from `calls`.
6. WHEN scanning `p_gen_bill`, THE Scanner SHALL return the calls `f_units`, `f_enrg_chg`, `f_fix_chg`, `f_fpa`, `p_taxes`, `f_due_dt` and `f_lps`.
7. WHEN scanning `f_enrg_chg`, THE Scanner SHALL return an empty `calls` set.

### Requirement 10: Branch counting

**User Story:** As a tester, I want a branch count per unit, so that I can judge how many cases a unit needs.

#### Acceptance Criteria

1. THE Scanner SHALL count each `IF` and each `ELSIF` in Live_Code as one branch, in any letter case.
2. IF a unit contains no `IF` and no `ELSIF` in Live_Code, THEN THE Scanner SHALL return 0 for `branches`.
3. WHEN `END IF` appears in Live_Code, THE Scanner SHALL omit it from the branch count.
4. WHEN scanning the legacy units, THE Scanner SHALL return 6 for `f_enrg_chg`, 2 for `f_lps` and 2 for `p_gen_bill`.
5. WHEN `IF` or `ELSIF` appears only in a comment or a string literal, THE Scanner SHALL omit it from the branch count.

### Requirement 11: Exception handling and swallowed errors

**User Story:** As a risk reviewer, I want handled and swallowed exceptions listed, so that silent failures are flagged in the autopsy.

#### Acceptance Criteria

1. WHEN Live_Code contains `WHEN <name> THEN` inside the Exception_Section, THE Scanner SHALL add the upper-case name to `exceptions_handled`.
2. IF a unit has no Exception_Section, THEN THE Scanner SHALL return an empty `exceptions_handled` and SHALL set `swallows_errors` to False.
3. WHEN scanning the legacy units, THE Scanner SHALL return `{NO_DATA_FOUND}` for `f_fpa`, `{NO_DATA_FOUND, OTHERS}` for `p_gen_bill` and an empty set for `f_units`.
4. WHEN a `WHEN OTHERS THEN` handler body consists only of `NULL;`, ignoring whitespace and comments, THE Scanner SHALL set `swallows_errors` to True.
5. WHEN no such handler exists, THE Scanner SHALL set `swallows_errors` to False.
6. WHEN scanning `f_fpa`, whose only handler returns 0 for `NO_DATA_FOUND`, THE Scanner SHALL set `swallows_errors` to False.
7. WHEN scanning `p_gen_bill`, THE Scanner SHALL set `swallows_errors` to True.
8. WHEN a `WHEN` occurs outside the Exception_Section or inside an `IF` or `CASE` expression, THE Scanner SHALL omit it from `exceptions_handled`.
9. WHEN a `WHEN` occurs only in a comment or a string literal, THE Scanner SHALL omit it from `exceptions_handled`.

### Requirement 12: Global variable use

**User Story:** As a migration engineer, I want to know which units read package globals, so that hidden state is visible.

#### Acceptance Criteria

1. WHEN Live_Code uses the name of a package global as a Whole_Word, THE Scanner SHALL add that name to `globals_used`.
2. WHEN a longer identifier contains a global name (for example `g_dbg_level` for the global `g_dbg`), THE Scanner SHALL omit that global from `globals_used`.
3. THE Scanner SHALL list each global once in `globals_used`.
4. IF a unit uses no package global, THEN THE Scanner SHALL return an empty `globals_used`.
5. WHEN scanning `f_units`, THE Scanner SHALL include `g_dbg`.
6. WHEN a global name appears only in a comment or a string literal, THE Scanner SHALL omit it from `globals_used`.

### Requirement 13: Robustness on unseen code

**User Story:** As a tester, I want the scanner to behave on code it was not written for, so that the tool generalises beyond one package.

#### Acceptance Criteria

1. WHEN a package other than `billing_pkg` is loaded, THE Exhumer SHALL return its name, units and line ranges using the same rules as for `billing_pkg`.
2. WHEN the body of `tricky_pkg.f_x` is scanned, THE Scanner SHALL report 1.25 and SHALL omit 12.5 (in a block comment), 7 (in a line comment) and 99 (in a string literal).
3. WHEN the body of `tricky_pkg.f_x` is scanned, THE Scanner SHALL return the string literal `rate 99 -- not a comment` and empty `tables_read` and `tables_written`.
4. WHEN keywords are written in upper, lower or mixed case, THE Exhumer and THE Scanner SHALL return the same results for each.
5. IF the body text contains no recognisable `PACKAGE BODY` header, THEN THE Exhumer SHALL raise an error.

### Requirement 14: Scope and verification

**User Story:** As the project owner, I want a dependency-free scanner proven by the existing tests, so that the Autopsy stage can trust it.

#### Acceptance Criteria

1. THE Exhumer and THE Scanner SHALL import only the Python standard library, with no `oracledb`, `streamlit`, `hypothesis` or language-model client imports.
2. THE Scanner SHALL return identical Facts for identical input across separate Python processes.
3. THE Exhumer and THE Scanner SHALL make no network calls.
4. THE Scanner feature SHALL leave `tests/test_autopsy_scanner.py` byte-identical to its original content.
5. WHEN `.venv\Scripts\python.exe -m pytest -q` is run with `ORACLE_DSN` unset, THE test suite SHALL pass every test in `tests/test_autopsy_scanner.py` with zero failed, errored and skipped tests.
6. IF any test in `tests/test_autopsy_scanner.py` fails, THEN THE test run SHALL exit with a non-zero status and name each failing test.

### Requirement 15: DUAL is not a table

**User Story:** As a migration engineer, I want Oracle's dummy table left out of the dependency graph, so that no fake table appears.

#### Acceptance Criteria

1. WHEN Live_Code contains `FROM DUAL` or `JOIN DUAL`, in any letter case and with or without a schema prefix, THE Scanner SHALL omit `DUAL` from `tables_read`.
2. WHEN a unit also reads other tables, THE Scanner SHALL still report those tables.

### Requirement 16: FROM inside EXTRACT and TRIM is not a table read

**User Story:** As a migration engineer, I want function syntax kept out of the table list, so that `EXTRACT(YEAR FROM d)` does not create a table called `d`.

#### Acceptance Criteria

1. WHEN `FROM` appears directly inside the parentheses of `EXTRACT(...)` or `TRIM(...)` in Live_Code, THE Scanner SHALL omit the word after it from `tables_read`.
2. WHEN a real `FROM` or `JOIN` appears in the same statement outside those parentheses, or inside the parentheses of a subquery, THE Scanner SHALL still report its table.
3. THE Scanner SHALL match `EXTRACT` and `TRIM` case-insensitively and as whole words.

### Requirement 17: Datatype sizes are not constants

**User Story:** As a migration engineer, I want `VARCHAR2(100)` and `NUMBER(12,2)` kept out of the business constants, so that column sizes are not mistaken for rules.

#### Acceptance Criteria

1. WHEN a numeric literal sits inside the parentheses that directly follow a datatype name (`VARCHAR2`, `VARCHAR`, `NVARCHAR2`, `CHAR`, `NCHAR`, `NUMBER`, `NUMERIC`, `DECIMAL`, `DEC`, `FLOAT`, `RAW`, `TIMESTAMP`, `UROWID`), THE Scanner SHALL omit it from `constants`.
2. WHEN a numeric literal is an argument of an ordinary function such as `SUBSTR(v, 1, 4)`, THE Scanner SHALL report it.
3. THE Scanner SHALL match the datatype names case-insensitively and as whole words, so `TO_NUMBER(5)` still reports 5.

### Requirement 18: Sign of a numeric literal

**User Story:** As a migration engineer, I want `-250` reported as minus 250 and `a - 1` as plain 1, so that constants carry the real value of the rule.

#### Acceptance Criteria

1. WHEN a minus sign is a unary operator, THE Scanner SHALL report the literal with a negative `Decimal` value, and SHALL set `line` and `col` to the position of the minus sign. A minus is unary when the previous code character is not an operand end (an identifier character, a digit or `)`), or when the previous word is one of `RETURN`, `THEN`, `ELSE`, `AND`, `OR`, `NOT`, `IN`, `WHEN`, `BETWEEN`, `DEFAULT`.
2. WHEN a minus sign is a binary subtraction (`a - 1`, `v-2`), THE Scanner SHALL report the literal as positive.
3. Whitespace between a unary minus and its literal SHALL not change the result.
4. Examples: `< -1` gives -1, `:= -250` gives -250, `ROUND(x, -2)` gives -2, `x * -0.5` gives -0.5.
