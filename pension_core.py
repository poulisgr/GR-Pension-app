"""
pension_core.py  — PURE pension math (no GUI), shared by the desktop app and
the Streamlit web app. Everything here is deterministic and import-safe.
"""
from datetime import date

# =============================================================================
#  Date helpers
# =============================================================================
def parse_date(s):
    """European 'D/M/Y' (also '-' or '.'); 2-digit year <70 -> 20xx else 19xx."""
    parts = str(s).strip().replace("-", "/").replace(".", "/").split("/")
    d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
    if y < 100:
        y += 2000 if y < 70 else 1900
    return date(y, m, d)


def age_between(bd_str, d_str):
    return (parse_date(d_str) - parse_date(bd_str)).days / 365.25


# =============================================================================
#  Legislation tables
# =============================================================================
LAMBDA_BANDS = [
    (0, 15, 0.77), (15, 18, 0.84), (18, 21, 0.90), (21, 24, 0.96),
    (24, 27, 1.03), (27, 30, 1.21), (30, 33, 1.42), (33, 36, 1.59),
    (36, 39, 1.80), (39, 42, 2.00), (42, 100, 2.00),
]
# 2026 income-tax scale (9/20/26/34/44) + tax credit by children
TAX_BRACKETS = [(10000, 0.09), (10000, 0.20), (10000, 0.26),
                (10000, 0.34), (float("inf"), 0.44)]
TAX_CREDIT = {0: 777, 1: 810, 2: 900, 3: 1120}
# ΕΑΣ main (κύριες) — threshold = lower bound of band
EAS_MAIN = [(1468.02, .03), (1784.00, .06), (2097.00, .07), (2413.00, .09),
            (2727.00, .10), (3042.00, .12), (3357.00, .13), (3671.00, .14)]
# ΕΑΣ supplementary (επικουρικές)
EAS_SUPP = [(300.01, .03), (350.01, .04), (400.01, .05), (450.01, .06),
            (500.01, .07), (550.01, .08), (600.01, .09), (650.01, .10)]

# Fixed assumptions (defaults)
CHILDREN = 0
BUY_RATE = 0.20
HEALTH_RATE = 0.06
ETHNIKI_FULL = 446.86
NORMAL_AGE = 67.0
MAX_N = 6


# =============================================================================
#  Core math
# =============================================================================
def replacement_rate(total_years):
    pct = 0.0
    for yfrom, yto, rate in LAMBDA_BANDS:
        if total_years <= yfrom:
            break
        yrs = min(total_years, yto) - yfrom
        if yrs > 0:
            pct += yrs * rate
    return pct / 100.0


def income_tax_annual(annual_income, children=0):
    tax, remaining = 0.0, annual_income
    for width, rate in TAX_BRACKETS:
        if remaining <= 0:
            break
        taxed = min(remaining, width)
        tax += taxed * rate
        remaining -= taxed
    base = TAX_CREDIT.get(children, 1120 + 220 * max(0, children - 3))
    credit = base
    if annual_income > 12000:
        credit = max(0.0, base - 20.0 * ((annual_income - 12000) / 1000.0))
    return max(0.0, tax - credit)


def eas_flat(amount, table):
    rate = 0.0
    for threshold, r in table:
        if amount >= threshold:
            rate = r
        else:
            break
    return amount * rate


def eas_progressive(amount, table):
    total = 0.0
    for idx, (lower, r) in enumerate(table):
        upper = table[idx + 1][0] if idx + 1 < len(table) else float("inf")
        if amount <= lower:
            break
        total += (min(amount, upper) - lower) * r
    return total


def eas_contrib(amount, table, mode):
    return eas_progressive(amount, table) if mode == "progressive" else eas_flat(amount, table)


def avg_salary_new(s_avg, T0, sf, N):
    return s_avg if (T0 + N) == 0 else (s_avg * T0 + sf * N) / (T0 + N)


def net_pension(m, E, A, children, eas_main_tbl=EAS_MAIN, eas_mode="flat",
                health_rate=HEALTH_RATE, eas_on_epik=True):
    kyria = m + E
    gross = m + E + A
    eas_k = eas_contrib(kyria, eas_main_tbl, eas_mode)
    eas_e = eas_contrib(A, EAS_SUPP, eas_mode) if eas_on_epik else 0.0
    eas = eas_k + eas_e
    health = health_rate * (gross - eas)
    taxable = gross - eas - health
    tax = income_tax_annual(taxable * 12.0, children) / 12.0
    net = gross - eas - health - tax
    return dict(gross=gross, net=net, kyria=kyria, epik=A, taxable=taxable,
                tax=tax, eas_k=eas_k, eas_e=eas_e, eas=eas, health=health, m=m)


def scenario(T0, s_avg, sf, N, E, A, children=CHILDREN, eas_main_tbl=EAS_MAIN,
             eas_mode="flat", health_rate=HEALTH_RATE, eas_on_epik=True, P=0.0):
    lam = replacement_rate(T0 + P)
    pr_bef = T0 / (T0 + P) if (T0 + P) > 0 else 1.0
    m = lam * s_avg * pr_bef
    lamp = replacement_rate(T0 + N + P)
    sp = avg_salary_new(s_avg, T0, sf, N)
    pr_aft = (T0 + N) / (T0 + N + P) if (T0 + N + P) > 0 else 1.0
    mp = lamp * sp * pr_aft
    before = net_pension(m, E, A, children, eas_main_tbl, eas_mode, health_rate, eas_on_epik)
    after = net_pension(mp, E, A, children, eas_main_tbl, eas_mode, health_rate, eas_on_epik)
    return dict(lam=lam, lamp=lamp, m=m, mp=mp, s_new=sp,
                before=before, after=after, P=P, pr_bef=pr_bef, pr_aft=pr_aft,
                dm_gross=mp - m, dm_net=after["net"] - before["net"])


def buyout_cost(sf, N, rate=BUY_RATE, upfront_discount=0.0):
    return rate * 12.0 * sf * N * (1.0 - upfront_discount)


def sigma(dm_net, sf, N, L, disc_rate, growth, buy_rate=BUY_RATE, upfront_discount=0.0):
    B = 0.0
    for t in range(1, int(round(L)) + 1):
        B += 12.0 * dm_net * ((1 + growth) ** (t - 1)) / ((1 + disc_rate) ** t)
    K = buyout_cost(sf, N, buy_rate, upfront_discount)
    return B - K, B, K


def disc_growth(npv_mode, i):
    """real: constant dm, discount at i ; cancel: dm grows at i, discount at i."""
    return (i, i) if npv_mode == "cancel" else (i, 0.0)


def national_pension(T0, Y, X, EU, NEU, eu_counts=True,
                     ethniki_full=ETHNIKI_FULL, normal_age=NORMAL_AGE):
    """Εθνική σύνταξη: full × insurance-factor × residence(x/40) × early-penalty."""
    window = max(0.0, Y - 15.0)
    reducing = X - (EU if eu_counts else 0.0)
    residence = max(0.0, min(window - reducing, 40.0))
    frac_res = residence / 40.0
    ins_factor = 1.0 if T0 >= 20 else max(0.0, 1.0 - 0.02 * (20.0 - T0))
    months_early = max(0.0, (normal_age - Y)) * 12.0
    early_factor = max(0.0, 1.0 - 0.005 * months_early)
    E = ethniki_full * ins_factor * frac_res * early_factor
    return dict(E=E, residence=residence, frac_res=frac_res, ins_factor=ins_factor,
                months_early=months_early, early_factor=early_factor, window=window)


def breakeven_L(Ss, Ls):
    """Interpolated Σ=0 crossing (fractional L) given sampled Σ values."""
    if not Ss:
        return None
    if Ss[0] >= 0:
        return 0.0
    for j in range(1, len(Ls)):
        if Ss[j - 1] < 0 <= Ss[j]:
            return Ls[j - 1] + (0 - Ss[j - 1]) * (Ls[j] - Ls[j - 1]) / (Ss[j] - Ss[j - 1])
    return None


if __name__ == "__main__":
    # sanity: default web scenario (T0=35, <s>=3000, sf=1000, N=5, A=300, abroad=0)
    Y = age_between("05/10/1964", "1/1/28")
    npd = national_pension(35, Y, 0, 0, 0)
    r = scenario(35, 3000, 1000, 5, npd["E"], 300, P=0.0)
    disc, grow = disc_growth("real", 0.02)
    S, B, K = sigma(r["dm_net"], 1000, 5, 20, disc, grow, 0.20, 0.02)
    print(f"Y={Y:.2f}  E={npd['E']:.1f}  m={r['m']:.1f}  m'={r['mp']:.1f}  "
          f"dm_net={r['dm_net']:.2f}  Σ(L20)={S:.1f}")
