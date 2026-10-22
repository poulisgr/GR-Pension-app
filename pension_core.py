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
    (24, 27, 1.03), (27, 30, 1.21),
    (30, 33, 1.98),   # Καρβέλλης table from 1.10.2019 (was 1.42)
    (33, 36, 2.50),   # (was 1.59)
    (36, 100, 2.55),  # (was 1.80/2.00)
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
             eas_mode="flat", health_rate=HEALTH_RATE, eas_on_epik=True, P=0.0,
             A_after=None):
    lam = replacement_rate(T0 + P)
    pr_bef = T0 / (T0 + P) if (T0 + P) > 0 else 1.0
    m = lam * s_avg * pr_bef
    lamp = replacement_rate(T0 + N + P)
    sp = avg_salary_new(s_avg, T0, sf, N)
    pr_aft = (T0 + N) / (T0 + N + P) if (T0 + N + P) > 0 else 1.0
    mp = lamp * sp * pr_aft
    A_aft = A if A_after is None else A_after
    before = net_pension(m, E, A, children, eas_main_tbl, eas_mode, health_rate, eas_on_epik)
    after = net_pension(mp, E, A_aft, children, eas_main_tbl, eas_mode, health_rate, eas_on_epik)
    return dict(lam=lam, lamp=lamp, m=m, mp=mp, s_new=sp,
                before=before, after=after, P=P, pr_bef=pr_bef, pr_aft=pr_aft,
                A_before=A, A_after=A_aft, dm_gross=mp - m, dA_gross=A_aft - A,
                dm_net=after["net"] - before["net"])


def buyout_cost(sf, N, rate=BUY_RATE, upfront_discount=0.0):
    return rate * 12.0 * sf * N * (1.0 - upfront_discount)


def sigma(dm_net, sf, N, L, disc_rate, growth, buy_rate=BUY_RATE, upfront_discount=0.0,
          extra_cost=0.0):
    B = 0.0
    for t in range(1, int(round(L)) + 1):
        B += 12.0 * dm_net * ((1 + growth) ** (t - 1)) / ((1 + disc_rate) ** t)
    K = buyout_cost(sf, N, buy_rate, upfront_discount) + extra_cost
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


# Ράντες (Δχ) Γήρατος — Εθνική Αναλογιστική Αρχή, ΥΑ οικ.23123/785, περίοδος 2015-2020
# (ΑΔΑ Ω9Ξ5465Θ1Ω-8ΣΖ). Life-annuity divisor for the NDC Τμήμα Β, by age at retirement.
RANTES_GERATOS = {
    50: 27.735, 51: 27.143, 52: 26.548, 53: 25.949, 54: 25.347, 55: 24.742,
    56: 24.136, 57: 23.528, 58: 22.919, 59: 22.308, 60: 21.693, 61: 21.075,
    62: 20.453, 63: 19.827, 64: 19.197, 65: 18.565, 66: 17.931, 67: 17.297,
    68: 16.665, 69: 16.033, 70: 15.401, 71: 14.768, 72: 14.132, 73: 13.495,
    74: 12.860, 75: 12.232, 76: 11.613, 77: 11.006, 78: 10.413, 79: 9.837, 80: 9.281,
}


def annuity_rate(age):
    """Official Γήρατος ράντα (Δχ) by age, linearly interpolated for fractional ages."""
    ages = sorted(RANTES_GERATOS)
    if age <= ages[0]:
        return RANTES_GERATOS[ages[0]]
    if age >= ages[-1]:
        return RANTES_GERATOS[ages[-1]]
    lo = int(age)
    frac = age - lo
    return RANTES_GERATOS[lo] + frac * (RANTES_GERATOS[lo + 1] - RANTES_GERATOS[lo])


def supplementary_pension(s_ep, yrs_A, yrs_B, Y, accrual_A=0.0045, c_rate_B=0.06,
                          notional_yield=0.0, annuity_divisor=None, extra_A=0.0,
                          apply_penalty_A=True, full_pension_age=None):
    """Επικουρική (ΕΤΕΑΕΠ) — Ν.4052/2012 αρ.42, όπως τροποπ. από Ν.4488/2017 αρ.16.
       Τμήμα Α (χρόνος ≤31/12/2014, DB) = ⟨s_ep⟩ · (yrs_A+extra_A) · 0.45%, μειωμένο
         κατά 1/200 (0.5%) για κάθε μήνα που υπολείπεται από το όριο πλήρους
         συνταξιοδότησης, με ανώτατο όριο τα 5 έτη (60 μήνες = 30%).
       Τμήμα Β (χρόνος ≥1/1/2015, NDC) = συσσωρευμένες εισφορές / ράντα(Y) / 12.
         Δεν υπόκειται σε μείωση, ανεπηρέαστο από πλασματικά/εξωτερικό.
       extra_A = πλασματικά (αν εξαγοραστούν για επικουρική) + έτη εξωτερικού που
         προσμετρώνται στο Τμήμα Α (πριν το 2015). ράντα από τον επίσημο πίνακα
         εκτός αν δοθεί χειροκίνητο annuity_divisor."""
    yrs_A_eff = yrs_A + extra_A
    total_yrs = yrs_A_eff + yrs_B
    if full_pension_age is None:
        full_pension_age = 62.0 if total_yrs >= 40.0 else 67.0
    months_missing = (min(60.0, max(0.0, (full_pension_age - Y) * 12.0))
                      if apply_penalty_A else 0.0)
    pen = 1.0 - 0.005 * months_missing
    part_A = s_ep * yrs_A_eff * accrual_A * pen
    div = annuity_rate(Y) if annuity_divisor is None else annuity_divisor
    annual_contrib = c_rate_B * s_ep * 12.0
    if notional_yield > 1e-9:
        g = notional_yield
        capital_B = annual_contrib * (((1 + g) ** yrs_B - 1) / g)   # FV of contributions
    else:
        capital_B = annual_contrib * yrs_B
    part_B = capital_B / div / 12.0 if div > 0 else 0.0
    return dict(A=part_A + part_B, part_A=part_A, part_B=part_B, capital_B=capital_B,
                rante=div, pen_A=pen, months_missing=months_missing,
                full_age=full_pension_age, yrs_A_eff=yrs_A_eff, total_yrs=total_yrs)


if __name__ == "__main__":
    # sanity: default web scenario (T0=35, <s>=3000, sf=1000, N=5, A=300, abroad=0)
    Y = age_between("05/10/1964", "1/1/28")
    npd = national_pension(35, Y, 0, 0, 0)
    r = scenario(35, 3000, 1000, 5, npd["E"], 300, P=0.0)
    disc, grow = disc_growth("real", 0.02)
    S, B, K = sigma(r["dm_net"], 1000, 5, 20, disc, grow, 0.20, 0.02)
    print(f"Y={Y:.2f}  E={npd['E']:.1f}  m={r['m']:.1f}  m'={r['mp']:.1f}  "
          f"dm_net={r['dm_net']:.2f}  Σ(L20)={S:.1f}")
