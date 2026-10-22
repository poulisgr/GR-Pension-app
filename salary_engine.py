"""
EFKA average-salary (<s>) engine.
  <s> = Σ [ pension_relevant · min(gross, cap(year,type)) · CPI(year) ] / (Σ days / 25)
pension_relevant = 1 if Συνολικές Εισφορές != 0  (excludes BONUS / retroactive).
cap depends on insured-type: 'ΠΑΛΑΙΟΣ' (pre-1993) vs 'ΝΕΟΣ' (1993+).
Supports both PDF (parse_efka) and Excel (parse_excel_efka) from e-ΕΦΚΑ.
"""
from datetime import date
import os
import re

# ---------------------------------------------------------------------------
# Text→code lookup tables for the Excel format (Κλάδος/Πακέτο Κάλυψης and
# Τύπος Αποδοχών columns use full text descriptions instead of numeric codes).
# ---------------------------------------------------------------------------
EXCEL_KPK_MAP = {
    "ΜΙΚΤΑ, ΙΚΑ-ΤΕΑΜ":         "101",   # κύρια + επικουρική (IKA-TEAM)
    "ΜΙΚΤΑ":                    "103",   # κύρια/ασθένεια only, no επικ
    "ΑΠΛΑ ΜΙΚΤΑ ΠΛΗΡΗ":         "1011",  # κύρια/ασθένεια/ανεργία, no επικ
    "ΕΠΙΔΟΜΑ ΜΗΤΡΟΤΗΤΑΣ ΟΑΕΔ":  "224",   # not relevant
    "ΕΙΣΦΟΡΕΣ ΓΙΑ ΤΟΝ ΕΛΠΚ":   "899",   # ΕΛΠΚ account, not relevant
}

EXCEL_TYP_MAP = {
    "ΤΑΚΤΙΚΕΣ ΑΠΟΔΟΧΕΣ":       "01",
    "ΔΩΡΟ ΧΡΙΣΤΟΥΓΕΝΝΩΝ":       "03",
    "ΔΩΡΟ ΠΑΣΧΑ":               "04",
    "ΕΠΙΔΟΜΑ ΑΔΕΙΑΣ":           "05",
    "ΑΠΟΔΟΧΕΣ ΑΣΘΕΝΕΙΑΣ":       "08",
    "ΑΝΑΔΡΟΜΙΚΕΣ ΑΠΟΔΟΧΕΣ":     "09",
    "ΑΠΟΔΟΧΕΣ ΓΙΑ ΥΠ/ΣΜΟ ΕΛΠΚ":"97",
    "ΛΟΙΠΕΣ ΑΠΟΔΟΧΕΣ":          "99",   # unclassified; excluded from επικ
}


def _import_pdfplumber():
    try:
        import pdfplumber
        return pdfplumber
    except ModuleNotFoundError:
        raise SystemExit(
            "\n[!] Missing dependency 'pdfplumber'. Install it with:\n"
            "       python3 -m pip install pdfplumber\n"
            "    (use the SAME python you run this script with)\n")

# ---------------------------------------------------------------------------
# Ceiling (πλαφόν) by year and insured-type  (user-supplied table)
# ---------------------------------------------------------------------------
CAP_PALAIOS = {
    2002: 1947.50, 2003: 2015.50, 2004: 2116.25, 2005: 2219.75, 2006: 2310.75,
    2007: 2310.75, 2008: 2432.25, 2009: 2432.25, 2010: 2432.25, 2011: 2432.25,
    2012: 2432.25, 2013: 5543.55, 2014: 5543.55, 2015: 5543.55, 2016: 5543.55,
    2017: 5860.80, 2018: 5860.80, 2019: 6500.00, 2020: 6500.00, 2021: 6500.00,
    2022: 6500.00, 2023: 7126.94, 2024: 7373.53, 2025: 7572.62, 2026: 7761.94,
}
CAP_NEOS = {
    2002: 3895.00, 2003: 4031.00, 2004: 4571.12, 2005: 4795.12, 2006: 5006.16,
    2007: 5231.44, 2008: 5414.56, 2009: 5543.55, 2010: 5543.55, 2011: 5543.55,
    2012: 5543.55, 2013: 5543.55, 2014: 5543.55, 2015: 5543.55, 2016: 5543.55,
    2017: 5860.80, 2018: 5860.80, 2019: 6500.00, 2020: 6500.00, 2021: 6500.00,
    2022: 6500.00, 2023: 7126.94, 2024: 7373.53, 2025: 7572.62, 2026: 7761.94,
}


def cap_for(year, insured_type="ΠΑΛΑΙΟΣ"):
    table = CAP_NEOS if str(insured_type).upper().startswith(("Ν", "N")) else CAP_PALAIOS
    y = min(max(year, min(table)), max(table))     # clamp to [2002, 2026]
    return table[y]


# Fraction of the MONTHLY ceiling that applies to each earnings type:
#   Christmas (03) = 1 month -> full ;  Easter (04) & vacation (05) = half month.
CAP_FRACTION = {"04": 0.5, "05": 0.5}

# ---------------------------------------------------------------------------
# Contribution-code rules for the ΕΠΙΚΟΥΡΙΚΗ (Τμήμα Α) earnings base.
# Source: ΚΠΚ image rules + Ν.4488/2017 art.16 / ΥΑ οικ.23123/785.
# ---------------------------------------------------------------------------
EPIK_KPK   = "101"                          # only ΜΙΚΤΑ, ΙΚΑ-ΤΕΑΜ carries επικ contributions
EPIK_TYPES = {"01", "03", "04", "05", "09"} # 01=τακτικές, 03=ΔΧ, 04=ΔΠ, 05=επίδ.αδείας,
                                             # 09=αναδρομικές; excludes 08=ασθένεια etc.


def eff_cap(year, typ, insured_type="ΠΑΛΑΙΟΣ"):
    return cap_for(year, insured_type) * CAP_FRACTION.get(typ, 1.0)


# ---------------------------------------------------------------------------
# CPI parser (cumulative ΔτΚ factor by employment year)
# ---------------------------------------------------------------------------
def parse_cpi(pdf_path):
    pdfplumber = _import_pdfplumber()
    cpi = {}
    with pdfplumber.open(pdf_path) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)
    for line in text.splitlines():
        m = re.match(r"^\s*(19|20)(\d{2})\s+(-?\d+[.,]?\d*)\s+(\d+[.,]\d+)\s+(\d+[.,]\d+)\s*$",
                     line.strip())
        if m:
            cpi[int(m.group(1) + m.group(2))] = float(m.group(5).replace(",", "."))
    return cpi


# Hardcoded fallback: cumulative ΔτΚ, e-ΕΦΚΑ letter 1479/20-01-2026 (αποχώρηση 2026).
DEFAULT_CPI = {
    1970: 88.37648, 1971: 85.8024, 1972: 82.26501, 1973: 71.22512, 1974: 56.12696, 1975: 49.49468,
    1976: 43.68462, 1977: 38.9346, 1978: 34.60853, 1979: 29.0828, 1980: 23.28487, 1981: 18.70271,
    1982: 15.44402, 1983: 12.8486, 1984: 10.8427, 1985: 9.0886, 1986: 7.38911, 1987: 6.34803,
    1988: 5.59298, 1989: 4.91907, 1990: 4.0856, 1991: 3.41891, 1992: 2.94988, 1993: 2.57857,
    1994: 2.32513, 1995: 2.13511, 1996: 1.9733, 1997: 1.87042, 1998: 1.78475, 1999: 1.73953,
    2000: 1.68559, 2001: 1.63016, 2002: 1.57352, 2003: 1.5203, 2004: 1.47746, 2005: 1.4275,
    2006: 1.38323, 2007: 1.34425, 2008: 1.29007, 2009: 1.27464, 2010: 1.21727, 2011: 1.17805,
    2012: 1.16062, 2013: 1.17141, 2014: 1.18699, 2015: 1.20796, 2016: 1.21801, 2017: 1.20451,
    2018: 1.19702, 2019: 1.194, 2020: 1.20909, 2021: 1.19447, 2022: 1.08939, 2023: 1.05291,
    2024: 1.02482, 2025: 1.0,
}


def load_cpi(cpi_path=None):
    """Return (cpi_dict, used_default, source_label).
       Falls back to the hardcoded DEFAULT_CPI when no valid file is supplied."""
    if cpi_path and str(cpi_path).strip() and os.path.exists(cpi_path):
        cpi = parse_cpi(cpi_path)
        if cpi:
            return cpi, False, os.path.basename(cpi_path)
    return dict(DEFAULT_CPI), True, "built-in default (e-ΕΦΚΑ letter 1479, αποχώρηση 2026)"


# ---------------------------------------------------------------------------
# EFKA salary-PDF parser  (structure per image (9).png)  -- VALIDATE on real PDF
# ---------------------------------------------------------------------------
def _money(s):
    s = (s or "").replace("€", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0

def _date(s):
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", s or "")
    if not m:
        return None
    d, mo, y = map(int, m.groups())
    return date(y, mo, d)

def _row_from_cells(cells):
    """Parse one table row. Columns:
       Από, Έως, Έτη, Μήνες, Ημέρες, Τύπος, Κλάδος, Μικτές€, Εισφορές€, Α/Μ.
       We anchor on the two money (€) columns so empty Έτη/Μήνες/Ημέρες cells
       cannot shift the mapping (this is what caused the type-code-as-days bug)."""
    cells = [(c or "").strip() for c in cells]
    frm = _date(cells[0]) if cells else None
    if not frm:
        return None
    kpk = ""
    money_idxs = [i for i, c in enumerate(cells) if "€" in c]
    if len(money_idxs) >= 2:
        mi = money_idxs[0]
        miktes = _money(cells[money_idxs[0]])
        eisf = _money(cells[money_idxs[1]])
        typ = cells[mi - 2] if mi - 2 >= 0 else ""     # Τύπος  = 2 left of Μικτές
        kpk = cells[mi - 1] if mi - 1 >= 0 else ""     # ΚΠΚ    = 1 left of Μικτές
        days_s = cells[mi - 3] if mi - 3 >= 0 else ""   # Ημέρες = 3 left of Μικτές
    else:                                               # fallback: fixed positions
        get = lambda i: cells[i] if i < len(cells) else ""
        days_s, typ = get(4), get(5)
        kpk = get(3)                                    # old ΔΡΧ rows: kpk in pos 3
        miktes, eisf = _money(get(7)), _money(get(8))
    days = int(days_s) if days_s.isdigit() else 0
    return dict(**{"from": frm}, days=days, typ=typ, kpk=kpk, miktes=miktes, eisfores=eisf)


def parse_efka(pdf_path):
    """Parse the e-ΕΦΚΑ earnings PDF into row dicts (structure per image 9/14)."""
    pdfplumber = _import_pdfplumber()
    rows = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for cells in table:
                    r = _row_from_cells(cells)
                    if r:
                        rows.append(r)
    return rows


def parse_excel_efka(path):
    """Parse the e-ΕΦΚΑ earnings Excel into the same row-dict format as parse_efka.
       Columns used: 'Από', 'Ημέρες', 'Τύπος Αποδοχών', 'Κλάδος/Πακέτο Κάλυψης',
       'Μικτές αποδοχές'.  The Excel has no 'Συνολικές Εισφορές' column, so
       eisfores is set to miktes (pension_relevant = 1 whenever miktes > 0)."""
    try:
        import pandas as pd
    except ImportError:
        raise SystemExit(
            "\n[!] Missing dependency 'pandas'. Install it with:\n"
            "       python3 -m pip install pandas openpyxl\n")
    df = pd.read_excel(path, sheet_name=0,
                       engine="openpyxl" if str(path).lower().endswith("xlsx") else "xlrd")
    rows = []
    for _, r in df.iterrows():
        # --- date ---
        raw_from = r.get("Από") if hasattr(r, "get") else r["Από"]
        if pd.isna(raw_from):
            continue
        frm = (raw_from.date() if hasattr(raw_from, "date")
               else _date(str(raw_from)))
        if frm is None:
            continue
        # --- days ---
        try:
            days = int(float(r.get("Ημέρες", 0) or 0))
        except (ValueError, TypeError):
            days = 0
        # --- KPK code (text → numeric string) ---
        kpk_raw = str(r.get("Κλάδος/Πακέτο Κάλυψης") or "").strip()
        kpk = EXCEL_KPK_MAP.get(kpk_raw, kpk_raw)
        # --- earnings type code (text → numeric string) ---
        typ_raw = str(r.get("Τύπος Αποδοχών") or "").strip()
        typ = EXCEL_TYP_MAP.get(typ_raw, "")
        # --- amount ---
        miktes = _money(str(r.get("Μικτές αποδοχές") or ""))
        # no eisfores column → use miktes as proxy (pr=1 iff miktes>0)
        rows.append(dict(**{"from": frm}, days=days, typ=typ, kpk=kpk,
                         miktes=miktes, eisfores=miktes))
    return rows


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------
def compute_average_salary(rows, cpi, insured_type="ΠΑΛΑΙΟΣ", start_year=2002):
    """Only earnings from `start_year` onward count (law: ανταποδοτική from 2002)."""
    total_days = 0.0
    numerator = 0.0
    aug = []
    skipped = 0
    for r in rows:
        yr = r["from"].year
        if yr < start_year:
            skipped += 1
            continue
        cpi_f = cpi.get(yr, 1.0)
        cap = eff_cap(yr, r["typ"], insured_type)   # per-type ceiling (δώρα get ½)
        pr = 1 if abs(r["eisfores"]) > 1e-9 else 0
        capped = min(r["miktes"], cap)
        contrib = capped * cpi_f * pr
        numerator += contrib
        total_days += r["days"]
        aug.append({**r, "cpi": cpi_f, "cap": cap, "pr": pr,
                    "capped": capped, "contrib": contrib})
    months = total_days / 25.0
    s_avg = numerator / months if months else 0.0
    return s_avg, months, total_days, numerator, aug, skipped


def compute_average_salary_epik(rows, cpi, insured_type="ΠΑΛΑΙΟΣ",
                                 epik_start=2002, epik_end=2014):
    """Compute the επικουρική-specific pensionable earnings average ⟨s_ep⟩.
       Only rows with ΚΠΚ = '101' (ΜΙΚΤΑ, ΙΚΑ-ΤΕΑΜ) AND earnings type in
       EPIK_TYPES {01,03,04,05,09} from epik_start..epik_end are included.
       Returns (s_ep, months_ep, yrs_A_actual, aug_ep, stats) where:
         yrs_A_actual = months_ep / 12  (actual Τμήμα Α years, from data — may
                        differ from date-range years if ΚΠΚ=103 gaps exist)
         stats = dict with row counts for transparency."""
    total_days = 0.0
    numerator  = 0.0
    aug_ep = []
    stats  = dict(included=0, skip_year=0, skip_kpk=0, skip_type=0)
    for r in rows:
        yr = r["from"].year
        kpk = r.get("kpk", "")
        typ = r.get("typ", "")
        if yr < epik_start or yr > epik_end:
            stats["skip_year"] += 1; continue
        if kpk != EPIK_KPK:
            stats["skip_kpk"] += 1; continue
        if typ not in EPIK_TYPES:
            stats["skip_type"] += 1; continue
        cpi_f = cpi.get(yr, 1.0)
        cap   = eff_cap(yr, typ, insured_type)
        pr    = 1 if abs(r["eisfores"]) > 1e-9 else 0
        capped   = min(r["miktes"], cap)
        contrib  = capped * cpi_f * pr
        numerator  += contrib
        total_days += r["days"]
        stats["included"] += 1
        aug_ep.append({**r, "cpi": cpi_f, "cap": cap, "pr": pr,
                       "capped": capped, "contrib": contrib})
    months_ep     = total_days / 25.0
    yrs_A_actual  = months_ep / 12.0
    s_ep = numerator / months_ep if months_ep else 0.0
    return s_ep, months_ep, yrs_A_actual, aug_ep, stats


# ---------------------------------------------------------------------------
# SAMPLE rows transcribed from image (9).png  (2007-2009)
# ---------------------------------------------------------------------------
def _r(f, days, typ, miktes, eisf, kpk="101"):
    d, m, y = map(int, f.split("/"))
    return dict(**{"from": date(y, m, d)}, days=days, typ=typ, kpk=kpk,
                miktes=miktes, eisfores=eisf)

SAMPLE = [
    _r("01/12/2007", 25, "01", 4945.00, 1019.99), _r("01/12/2007", 0, "03", 5151.01, 1019.99),
    _r("01/01/2008", 25, "01", 4945.00, 1019.99), _r("01/01/2008", 0, "17", 0.00, 168.42),
    _r("01/02/2008", 25, "01", 4945.00, 1019.99), _r("01/02/2008", 0, "10", 15176.67, 0.00),
    _r("01/03/2008", 25, "01", 5093.00, 1019.99), _r("01/03/2008", 0, "10", 31.28, 0.00),
    _r("01/04/2008", 25, "01", 5093.00, 1019.99), _r("01/04/2008", 0, "04", 2652.59, 509.99),
    _r("01/04/2008", 0, "10", 2596.00, 0.00),     _r("01/04/2008", 0, "09", 173.75, 0.00),
    _r("01/05/2008", 25, "01", 5093.00, 1019.99), _r("01/06/2008", 25, "01", 5348.00, 1050.61),
    _r("01/06/2008", 0, "05", 2674.00, 525.31),   _r("01/07/2008", 25, "01", 5348.00, 1050.61),
    _r("01/07/2008", 0, "10", 777.00, 0.00),      _r("01/08/2008", 25, "01", 5348.00, 1050.61),
    _r("01/09/2008", 25, "01", 5348.00, 1050.61), _r("01/10/2008", 0, "10", 1568.43, 0.00),
    _r("01/10/2008", 25, "01", 5348.00, 1071.65), _r("01/11/2008", 25, "01", 5348.00, 1071.65),
    _r("01/12/2008", 25, "01", 5348.00, 1071.65), _r("01/12/2008", 0, "03", 5570.80, 1071.65),
    _r("01/01/2009", 25, "01", 5348.00, 1071.65), _r("01/01/2009", 0, "10", 31.28, 0.00),
    _r("01/02/2009", 25, "01", 5348.00, 1071.65), _r("01/03/2009", 25, "01", 5348.00, 1071.65),
    _r("01/03/2009", 0, "10", 21901.06, 0.00),    _r("01/04/2009", 0, "04", 2785.40, 535.82),
]


if __name__ == "__main__":
    print("salary_engine.py is a LIBRARY module — nothing to run here.\n"
          "Use:  python3 salary_gui.py   (GUI)   or   python3 compute_s.py   (CLI).")
