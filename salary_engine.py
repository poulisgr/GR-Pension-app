"""
EFKA average-salary (<s>) engine.
  <s> = Σ [ pension_relevant · min(gross, cap(year,type)) · CPI(year) ] / (Σ days / 25)
pension_relevant = 1 if Συνολικές Εισφορές != 0  (excludes BONUS / retroactive).
cap depends on insured-type: 'ΠΑΛΑΙΟΣ' (pre-1993) vs 'ΝΕΟΣ' (1993+).
"""
from datetime import date
import os
import re


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
    money_idxs = [i for i, c in enumerate(cells) if "€" in c]
    if len(money_idxs) >= 2:
        mi = money_idxs[0]
        miktes = _money(cells[money_idxs[0]])
        eisf = _money(cells[money_idxs[1]])
        typ = cells[mi - 2] if mi - 2 >= 0 else ""     # Τύπος  = 2 left of Μικτές
        days_s = cells[mi - 3] if mi - 3 >= 0 else ""   # Ημέρες = 3 left of Μικτές
    else:                                               # fallback: fixed positions
        get = lambda i: cells[i] if i < len(cells) else ""
        days_s, typ = get(4), get(5)
        miktes, eisf = _money(get(7)), _money(get(8))
    days = int(days_s) if days_s.isdigit() else 0
    return dict(**{"from": frm}, days=days, typ=typ, miktes=miktes, eisfores=eisf)


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


# ---------------------------------------------------------------------------
# SAMPLE rows transcribed from image (9).png  (2007-2009)
# ---------------------------------------------------------------------------
def _r(f, days, typ, miktes, eisf):
    d, m, y = map(int, f.split("/"))
    return dict(**{"from": date(y, m, d)}, days=days, typ=typ, miktes=miktes, eisfores=eisf)

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
