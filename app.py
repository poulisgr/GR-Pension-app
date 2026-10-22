"""
app.py — Streamlit web front-end for the Greek pension strategy calculator.
Reuses pension_core.py (pure math) and salary_engine.py (EFKA <s>).
Run locally:  streamlit run app.py
Deploy:       see render.yaml  (Render web service)
"""
import matplotlib
matplotlib.use("Agg")
from matplotlib.figure import Figure
import streamlit as st
from datetime import date

import pension_core as pc
import salary_engine as se

ACCENT, C_NET, C_NEG, C_GRID = "#1a4f8b", "#2e8b57", "#b22222", "#d0d5da"
BLUE, ORANGE = "#17a2b8", "#e67e22"
SF_COLORS = ["#1a4f8b", "#2e8b57", "#c77d00", "#8e44ad", "#17a2b8", "#b22222"]

st.set_page_config(page_title="Greek Pension Strategy", layout="wide")
st.session_state.setdefault("s_box", 3000.0)
st.session_state.setdefault("s_ep_box", 3000.0)   # επικ. earnings base
st.session_state.setdefault("yrs_A_box", 0.0)     # 0 = use date-derived split


# ----------------------------------------------------------------------------
#  Sidebar inputs
# ----------------------------------------------------------------------------
def sidebar_inputs():
    sb = st.sidebar
    sb.title("INPUTS")
    sb.subheader("Retirement")
    T0 = sb.number_input("T0 — years as employee", value=35.0, step=1.0)
    D = sb.text_input("D — pension start date (d/m/y)", "1/1/28")
    BD = sb.text_input("BD — birthday (d/m/y)", "05/10/1964")

    sb.subheader("Simulation")
    s = sb.number_input("⟨s⟩ — avg salary (€/mo)", step=50.0, key="s_box")
    sf = sb.number_input("sf — buy-out salary (€/mo)", value=1000.0, step=50.0)
    N = sb.slider("N — πλασματικά έτη (bought)", 0, pc.MAX_N, 5)
    L = sb.slider("L — life expectancy beyond D (yrs)", 0, 25, 20)
    i = sb.number_input("i — inflation / discount (%)", value=2.0, step=0.25,
                        format="%.2f") / 100.0
    dsf = sb.number_input("Δsf — step for sf-curve family (€)", value=200.0, step=50.0)

    sb.subheader("Επικουρική (A)")
    compute_epik = sb.checkbox("Compute A (Τμήμα Α + Β)  —  else manual", value=False)
    A = ep = None
    if compute_epik:
        auto_rante = sb.checkbox("Auto ράντα from official table (by age)", value=True)
        ep = dict(
            epik_start=sb.text_input("επικ. insurance start (d/m/y)", "1/9/1997"),
            yrs_A_data=sb.number_input(
                "yrs_A from EFKA data (0 = use date-derived)",
                min_value=0.0, step=0.1, format="%.2f", key="yrs_A_box"),
            s_ep=sb.number_input("⟨s_ep⟩ — επικ. earnings base (€/mo)",
                                 step=50.0, key="s_ep_box"),
            accrual_A=sb.number_input("Τμήμα Α accrual (%)", value=0.45,
                                      step=0.05, format="%.2f") / 100.0,
            c_rate_B=sb.number_input("Τμήμα Β contribution rate (%)", value=6.0,
                                     step=0.5, format="%.2f") / 100.0,
            notional_yield=sb.number_input("Τμήμα Β notional yield (%)", value=0.0,
                                           step=0.5, format="%.2f") / 100.0,
            annuity_div=(None if auto_rante else
                         sb.number_input("manual ράντα divisor", value=19.827, step=0.1)),
            penalty_A=sb.checkbox("early-retirement penalty on Τμήμα Α (1/200·mo, ≤5y)",
                                  value=True),
            epik_exagora=sb.checkbox("εξαγορά πλασματικών για επικουρική (+N στο Τμήμα Α)",
                                     value=False),
            epik_rate=sb.number_input("επικ. εξαγορά rate (%)", value=6.0,
                                      step=0.5, format="%.2f") / 100.0,
        )
    else:
        A = sb.number_input("A — επικουρική (€/mo)", value=300.0, step=50.0)

    sb.subheader("Abroad")
    X = float(sb.slider("X — total years abroad", 0, 25, 0))
    EU = float(sb.slider("EU — thereof pensionable in EU", 0, 25, 0))
    NEU = float(sb.slider("NEU — thereof pensionable non-EU", 0, 25, 0))
    eu_counts = sb.checkbox("EU years count as GR residence", True)
    totalize = sb.checkbox("Apply abroad totalization (EU+NEU → λ, pro-rata)", True)

    sb.subheader("Assumptions")
    npv_mode = sb.radio("NPV convention", ["real", "cancel"],
                        format_func=lambda m: "Real: constant dm, discount at i"
                        if m == "real" else "Nominal: dm grows at i, discount at i")
    eas_mode = sb.radio("ΕΑΣ calculation", ["flat", "progressive"],
                        format_func=lambda m: "Flat: whole amount (current law)"
                        if m == "flat" else "Progressive: marginal (pending)")
    eas_on_epik = sb.checkbox("ΕΑΣ applies to επικουρική too", True)
    pay_upfront = sb.checkbox("Pay buy-out upfront (−2%)", True)
    return dict(T0=T0, D=D, BD=BD, s=s, sf=sf, N=N, L=L, A=A, i=i, dsf=dsf,
                X=X, EU=EU, NEU=NEU, eu_counts=eu_counts, totalize=totalize,
                npv_mode=npv_mode, eas_mode=eas_mode, eas_on_epik=eas_on_epik,
                upfront=0.02 if pay_upfront else 0.0,
                compute_epik=compute_epik, ep=ep)


# ----------------------------------------------------------------------------
#  Summary (Greek)
# ----------------------------------------------------------------------------
def summary_text(v, r, npd, S, B, K, sp=None, k_epik=0.0, m_base=None, A_base=None):
    b, a = r["before"], r["after"]
    sep = "-" * 42
    T0, N, P = v["T0"], v["N"], r["P"]
    lines = [
        "ΠΟΣΟΣΤΟ ΑΝΑΠΛΗΡΩΣΗΣ",
        f"  λ   (έτη {T0+P:.0f}=T0+P)     = {r['lam']*100:6.2f}%",
        f"  λ'  (έτη {T0+N+P:.0f}=T0+N+P) = {r['lamp']*100:6.2f}%",
        "ΜΕΣΟΣ ΟΡΟΣ ΣΥΝΤΑΞΙΜΩΝ ΑΠΟΔΟΧΩΝ",
        f"  <s>  (τρέχον) = {v['s']:>8.0f}  €/mo",
        f"  <s'> (νέο)    = {r['s_new']:>8.1f}  €/mo",
    ]
    if P > 0:
        lines += [f"ΕΤΗ ΕΞΩΤΕΡΙΚΟΥ P = {P:.0f} (EU {v['EU']:.0f} + NEU {v['NEU']:.0f})",
                  f"  pro-rata: πριν {r['pr_bef']*100:.1f}%  μετά {r['pr_aft']*100:.1f}%"]
    lines += [
        sep, "ΕΘΝΙΚΗ ΣΥΝΤΑΞΗ  E",
        f"  βασική × έτη ασφ.        = {pc.ETHNIKI_FULL*npd['ins_factor']:>7.1f}",
        f"  απομείωση λόγω διαμονής  = {npd['residence']:.1f}/40 = {npd['frac_res']*100:.1f}%",
        f"  απομείωση λόγω πρόωρης   = {npd['months_early']:.0f} μήνες ×{npd['early_factor']*100:.1f}%",
        f"  => E = {npd['E']:>7.1f}  €/mo",
    ]
    if sp is not None:
        abroad_A = sp["yrs_A_eff"] - sp["yrs_A"]
        lines += [
            sep, "ΕΠΙΚΟΥΡΙΚΗ ΣΥΝΤΑΞΗ  A (υπολογ.)",
            f"  Τμήμα Α {sp['yrs_A_eff']:.2f}y ×0.45% (μείωση {(1-sp['pen_A'])*100:.0f}%) = {sp['part_A']:>7.1f}",
        ]
        if abroad_A > 0.01:
            lines.append(f"    (= {sp['yrs_A']:.2f}y ΕΛ + {abroad_A:.2f}y εξωτ.)")
        lines += [
            f"  Τμήμα Β {sp['yrs_B']:.2f}y NDC (ράντα {sp['rante']:.3f}) = {sp['part_B']:>7.1f}",
            f"  => A = {sp['A']:>7.1f}  €/mo",
        ]
    if m_base is not None:
        lines += [
            sep, "ΣΥΝΘΕΣΗ ΑΠΟ ΒΑΣΗ (T0, χωρίς εξωτ/πλασμ)",
            f"  m βάση = {m_base:>7.1f}   dm (εξωτ+πλασμ) = {r['mp']-m_base:>7.2f}",
            f"  A βάση = {A_base:>7.1f}   dA (εξωτ+πλασμ) = {r['A_after']-A_base:>7.2f}",
        ]
    lines += [
        sep, "ΑΝΤΑΠΟΔΟΤΙΚΗ ΣΥΝΤΑΞΗ",
        f"  m  (πριν)  = {r['m']:>8.1f}  €/mo",
        f"  m' (μετά)  = {r['mp']:>8.1f}  €/mo",
        sep, "ΔΙΑΦΟΡΑ ΑΠΟ ΕΞΑΓΟΡΑ N πλασματικών",
        f"  μικτή dm (ανταποδ.) = {r['dm_gross']:>7.2f}  €/mo",
    ]
    if abs(r["dA_gross"]) > 0.01:
        lines.append(f"  μικτή dA (επικ.)    = {r['dA_gross']:>7.2f}  €/mo")
    lines += [
        f"  ΚΑΘΑΡΟ όφελος       = {r['dm_net']:>7.2f}  €/mo",
        sep, "ΚΡΑΤΗΣΕΙΣ ΒΑΣΗΣ (πριν)",
        f"  Υγεία 6% = {b['health']:>7.1f}   ΕΑΣ = {b['eas']:>6.1f}",
        f"  Φόρος    = {b['tax']:>7.1f}",
        f"  καθαρή σύνταξη πριν = {b['net']:>8.1f}  €/mo",
        f"  καθαρή σύνταξη μετά = {a['net']:>8.1f}  €/mo",
        sep, "ΑΞΙΟΛΟΓΗΣΗ ΕΞΑΓΟΡΑΣ",
        f"  K  κόστος εξαγοράς      = {K:>9.1f} €",
    ]
    if k_epik > 0.01:
        lines.append(f"     (εκ των οποίων επικ. = {k_epik:>7.1f} €)")
    lines += [
        f"  B  παρούσα αξία οφέλους = {B:>9.1f} €",
        f"  Σ = B - K               = {S:>9.1f} €",
        "  → ΣΥΜΦΕΡΕΙ" if S > 0 else "  → όχι ακόμα θετικό",
    ]
    return "\n".join(lines)


# ----------------------------------------------------------------------------
#  Charts
# ----------------------------------------------------------------------------
def _epik_A(ctx, extra_A):
    """Compute the επικουρική (dict) for a given extra Τμήμα-Α years amount."""
    return pc.supplementary_pension(
        ctx["s_ep"], ctx["yrs_A"], ctx["yrs_B"], ctx["Y"],
        accrual_A=ctx["accrual_A"], c_rate_B=ctx["c_rate_B"],
        notional_yield=ctx["notional_yield"], annuity_divisor=ctx["annuity_div"],
        extra_A=extra_A, apply_penalty_A=ctx["penalty_A"])


def _kepik(v, sf, N, ctx):
    """One-off cost of buying N πλασματικά into the επικουρική (6% basis)."""
    if ctx and ctx.get("compute") and ctx.get("exagora"):
        return pc.buyout_cost(sf, N, ctx["epik_rate"], v["upfront"])
    return 0.0


def _scn(v, sf, N, E, P, ctx=None):
    """Scenario; when the επικ two-part model is active, A moves before→after
       (abroad always in Τμήμα Α; +N only if επικ-εξαγορά is on)."""
    if ctx and ctx.get("compute"):
        A_before = _epik_A(ctx, ctx["extra_abroad"])["A"]
        extra_after = ctx["extra_abroad"] + (N if ctx.get("exagora") else 0.0)
        A_after = _epik_A(ctx, extra_after)["A"]
        return pc.scenario(v["T0"], v["s"], sf, N, E, A_before, pc.CHILDREN, pc.EAS_MAIN,
                           v["eas_mode"], pc.HEALTH_RATE, v["eas_on_epik"], P,
                           A_after=A_after)
    return pc.scenario(v["T0"], v["s"], sf, N, E, v["A"], pc.CHILDREN, pc.EAS_MAIN,
                       v["eas_mode"], pc.HEALTH_RATE, v["eas_on_epik"], P)


def fig_breakdown(v, r, E, m_base, A_base):
    """Decomposition: fixed pure base (E + A_base + m_base, i.e. T0 only, no abroad,
       no πλασματικά) + dm + dA (the ανταποδ./επικ. uplift from abroad+πλασματικά)
       − deductions → NET."""
    a = r["after"]
    dm = r["mp"] - m_base          # ανταποδοτική uplift from abroad + πλασματικά
    dA = r["A_after"] - A_base     # επικουρική uplift from abroad + πλασματικά
    steps = [("E\nΕθνική", E, C_NET), ("A βάση\nΕπικ.", A_base, C_NET),
             ("m βάση\nΑνταπ.", m_base, C_NET), ("dm\nεξωτ+πλασμ", dm, BLUE)]
    if abs(dA) > 0.01:
        steps.append(("dA\nεξωτ+πλασμ", dA, ORANGE))
    steps += [("ΕΑΣ", -a["eas"], C_NEG), ("Υγεία6%", -a["health"], C_NEG),
              ("Φόρος", -a["tax"], C_NEG)]
    labels = [s[0] for s in steps] + ["NET"]
    fig = Figure(figsize=(7.6, 5.2)); ax = fig.add_subplot(111)
    ymax = max(a["gross"], E + A_base + m_base + max(0.0, dm) + max(0.0, dA))
    ith = 0.055 * ymax; cum = 0.0
    for i, (lbl, val, c) in enumerate(steps):
        bot = cum if val >= 0 else cum + val
        ax.bar(i, abs(val), bottom=bot, width=0.68, color=c, edgecolor="#555", alpha=.92)
        ax.plot([i-0.34, i+0.66], [cum+val, cum+val], color="#aaa", lw=.8, ls="--")
        if abs(val) >= ith:
            ax.text(i, bot+abs(val)/2, f"{val:+.0f}", ha="center", va="center",
                    color="white", fontsize=8, fontweight="bold")
        else:
            ax.text(i, bot+abs(val)+0.012*ymax, f"{val:+.0f}", ha="center", va="bottom",
                    color=c, fontsize=7.5, fontweight="bold")
        cum += val
    ax.bar(len(steps), a["net"], width=0.68, color=ACCENT, edgecolor="#333")
    ax.text(len(steps), a["net"]/2, f"{a['net']:.0f}", ha="center", va="center",
            color="white", fontsize=10, fontweight="bold")
    ax.axhline(0, color="#333", lw=.8)
    ax.set_xticks(range(len(labels))); ax.set_xticklabels(labels, rotation=20, fontsize=7)
    ax.set_ylim(0, max(3500, ymax * 1.15)); ax.set_ylabel("€ / month")
    ax.set_title("Σύνθεση σύνταξης: βάση + (εξωτ+πλασμ) − κρατήσεις")
    ax.grid(axis="y", color=C_GRID, lw=.6); fig.tight_layout(); return fig


def fig_dm_vs_N(v, E, P, ctx=None):
    Ns = list(range(0, pc.MAX_N + 1))
    rs = [_scn(v, v["sf"], n, E, P, ctx) for n in Ns]
    g = [rr["dm_gross"] for rr in rs]
    nt = [rr["dm_net"] for rr in rs]
    fig = Figure(figsize=(7.6, 5.2)); ax = fig.add_subplot(111)
    ax.plot(Ns, g, "o-", color=ACCENT, label="μικτό dm (ανταποδ.)")
    if ctx and ctx.get("exagora"):
        ax.plot(Ns, [rr["dA_gross"] for rr in rs], "^-", color=ORANGE, label="μικτό dA (επικ.)")
    ax.plot(Ns, nt, "s-", color=C_NET, label="ΚΑΘΑΡΟ όφελος")
    ax.axvline(v["N"], color=C_NEG, ls="--", lw=1, label=f"N={v['N']}")
    ax.set_xticks(Ns); ax.set_ylim(0, 500); ax.set_xlabel("N"); ax.set_ylabel("Δ σύνταξη €/mo")
    ax.set_title("Διαφορά σύνταξης vs N"); ax.legend(); ax.grid(color=C_GRID, lw=.6)
    fig.tight_layout(); return fig


def fig_sigma_vs_L(v, E, P, disc, grow, ctx=None):
    Ls = list(range(0, 26)); fig = Figure(figsize=(7.6, 5.2)); ax = fig.add_subplot(111)
    for k, col in zip(range(6), SF_COLORS):
        sf = v["sf"] + k * v["dsf"]; rr = _scn(v, sf, v["N"], E, P, ctx)
        kep = _kepik(v, sf, v["N"], ctx)
        Ss = [pc.sigma(rr["dm_net"], sf, v["N"], L, disc, grow, pc.BUY_RATE, v["upfront"],
                       extra_cost=kep)[0] for L in Ls]
        be = pc.breakeven_L(Ss, Ls)
        lbl = f"sf={sf:.0f}" + (f"  BE≈{be:.1f}y" if be is not None else "  BE>25y")
        ax.plot(Ls, Ss, "-", color=col, lw=2.4 if k == 0 else 1.3, label=lbl)
        if be is not None:
            ax.plot(be, 0, "o", color=col, ms=7, zorder=5)
    ax.axhline(0, color="#333", lw=.9); ax.axvline(v["L"], color="#888", ls="--", lw=1)
    ax.set_xlabel("L (έτη)"); ax.set_ylabel("Σ = B − K (€)")
    ax.set_title(f"NPV vs L — 6 καμπύλες sf (N={v['N']})")
    ax.legend(fontsize=8, title=f"sf = input + k·Δsf (Δsf={v['dsf']:.0f})")
    ax.grid(color=C_GRID, lw=.6); fig.tight_layout(); return fig


def fig_sigma_vs_N(v, E, P, disc, grow, ctx=None):
    Ns = list(range(1, pc.MAX_N + 1)); fig = Figure(figsize=(7.6, 5.2)); ax = fig.add_subplot(111)
    for k, col in zip(range(6), SF_COLORS):
        sf = v["sf"] + k * v["dsf"]
        Ss = [pc.sigma(_scn(v, sf, n, E, P, ctx)["dm_net"], sf, n, v["L"], disc, grow,
                       pc.BUY_RATE, v["upfront"], extra_cost=_kepik(v, sf, n, ctx))[0]
              for n in Ns]
        ax.plot(Ns, Ss, "o-", color=col, lw=2.4 if k == 0 else 1.3, label=f"sf={sf:.0f}")
    ax.axhline(0, color="#333", lw=.9); ax.set_xticks(Ns)
    ax.set_xlabel("N"); ax.set_ylabel("Σ = B − K (€)")
    ax.set_title(f"Σ vs N στο L={v['L']} έτη")
    ax.legend(fontsize=8, title=f"sf = input + k·Δsf (Δsf={v['dsf']:.0f})")
    ax.grid(color=C_GRID, lw=.6); fig.tight_layout(); return fig


# ----------------------------------------------------------------------------
#  Salary <s> tool
# ----------------------------------------------------------------------------
def salary_tab():
    st.subheader("Υπολογισμός μέσου μισθού ⟨s⟩ από e-ΕΦΚΑ")
    c1, c2 = st.columns(2)
    sal_file = c1.file_uploader("EFKA earnings — PDF or Excel (.xlsx/.xls)", type=["pdf","xlsx","xls"])
    cpi_pdf = c2.file_uploader("CPI (ΔτΚ) PDF — blank = built-in 2026 default", type="pdf")
    insured = st.radio("Insured type", ["ΠΑΛΑΙΟΣ", "ΝΕΟΣ"], horizontal=True)
    start_year = st.number_input("Start year (law: 2002)", value=2002, step=1)
    if st.button("Compute ⟨s⟩", type="primary"):
        import tempfile, os
        try:
            if cpi_pdf is not None:
                tf = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
                tf.write(cpi_pdf.read()); tf.close()
                cpi, used_default, src = se.load_cpi(tf.name); os.unlink(tf.name)
            else:
                cpi, used_default, src = se.load_cpi(None)
            if used_default:
                st.info("No CPI file — using built-in e-ΕΦΚΑ 2026 default indices.")
            if sal_file is not None:
                ext = sal_file.name.lower().rsplit(".", 1)[-1]
                tf = tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}")
                tf.write(sal_file.read()); tf.close()
                rows = (se.parse_excel_efka(tf.name)
                        if ext in ("xlsx", "xls")
                        else se.parse_efka(tf.name))
                os.unlink(tf.name); srcname = sal_file.name
            else:
                rows = se.SAMPLE; srcname = "built-in SAMPLE (2007–2009)"
            s_val, months, days, num, aug, skipped = se.compute_average_salary(
                rows, cpi, insured, int(start_year))
            st.session_state["last_s"] = s_val
            st.success(f"⟨s⟩ = {s_val:,.2f} €/mo   "
                       f"(source {srcname}; {days:,.0f} days → {months:,.2f} months; "
                       f"CPI: {src}; before {int(start_year)} ignored: {skipped})")
            # --- επικουρική earnings base (ΚΠΚ=101, types 01/03/04/05/09, 2002-2014) ---
            s_ep, months_ep, yrs_A_actual, _, stats = se.compute_average_salary_epik(
                rows, cpi, insured)
            st.session_state["last_s_ep"]  = s_ep
            st.session_state["last_yrs_A"] = yrs_A_actual
            if s_ep > 0:
                # earliest date in data → suggest as epik_start for correct yrs_A
                epik_dates = [r["from"] for r in rows if r.get("kpk") == se.EPIK_KPK
                              and 2002 <= r["from"].year <= 2014]
                all_dates  = [r["from"] for r in rows if r["from"].year >= 1990]
                earliest   = min(all_dates).strftime("%d/%m/%Y") if all_dates else "?"
                st.info(
                    f"**⟨s_ep⟩ (Τμήμα Α base, 2002–2014)** = **{s_ep:,.2f} €/mo**  |  "
                    f"KPK=101 months 2002–2014: {yrs_A_actual*12:.0f} mos = {yrs_A_actual:.2f} y (informational)  |  "
                    f"excl. ΚΠΚ≠101: {stats['skip_kpk']}  excl. type: {stats['skip_type']}"
                )
                st.caption(
                    f"ℹ Earliest date in data: **{earliest}**. "
                    f"Set **'επικ. insurance start'** in the sidebar to your actual career start "
                    f"to get the correct yrs_A (all insured years up to 2014, not just 2002-2014).")
            else:
                st.warning("No ΚΠΚ=101 rows found in 2002–2014 — ⟨s_ep⟩ could not be computed. "
                           "Check that the PDF covers that period.")
        except SystemExit as e:
            st.error(str(e))
        except Exception as e:
            st.error(f"Error: {e}")
    if "last_s" in st.session_state:
        st.button(f"✓ Use ⟨s⟩ = {st.session_state['last_s']:,.2f} in the calculator",
                  on_click=_apply_s)
        if st.session_state.pop("s_copied", False):
            st.success("⟨s⟩ copied to the Simulation input (see the sidebar).")
    if st.session_state.get("last_yrs_A", 0) > 0:
        s_ep_last  = st.session_state["last_s_ep"]
        yrs_A_last = st.session_state["last_yrs_A"]
        st.button(
            f"✓ Apply ⟨s_ep⟩ = {s_ep_last:,.2f} €/mo → Τμήμα Α earnings base",
            on_click=_apply_epik)
        if st.session_state.pop("epik_copied", False):
            st.success("⟨s_ep⟩ applied — set 'επικ. insurance start' in the sidebar "
                       "to your career start date (for correct yrs_A), "
                       "then enable 'Compute A'.")


def _apply_s():
    """on_click callback: push the computed <s> into the sidebar input key."""
    st.session_state["s_box"] = float(round(st.session_state.get("last_s", 0.0), 2))
    st.session_state["s_copied"] = True


def _apply_epik():
    """on_click callback: push data-derived s_ep into the sidebar key.
       yrs_A is intentionally NOT pushed here — it must come from the
       'επικ. insurance start' date field (career start → 31/12/2014),
       per the official rule: earnings base = 2002-2014 data, but years
       counted = ALL insured time up to 2014 from career start."""
    st.session_state["s_ep_box"]  = float(round(st.session_state.get("last_s_ep", 0.0), 2))
    st.session_state["epik_copied"] = True


# ----------------------------------------------------------------------------
#  Main
# ----------------------------------------------------------------------------
def main():
    st.title("Greek Pension Strategy — εξαγορά πλασματικών ετών")
    v = sidebar_inputs()
    try:
        Y = pc.age_between(v["BD"], v["D"])
    except Exception:
        st.error("Check the date formats (d/m/y) for D and BD."); return
    npd = pc.national_pension(v["T0"], Y, v["X"], v["EU"], v["NEU"], v["eu_counts"])
    E = npd["E"]
    P = (v["EU"] + v["NEU"]) if v["totalize"] else 0.0

    # ---- επικουρική A: computed (two-part, dynamic) or manual ----
    sp = None
    epik_ctx = None
    if v["compute_epik"]:
        ep = v["ep"]
        try:
            es, dd = pc.parse_date(ep["epik_start"]), pc.parse_date(v["D"])
        except Exception:
            st.error("Check the επικ. insurance start date format (d/m/y)."); return
        boundary = date(2015, 1, 1)
        yrs_A = max(0.0, (min(dd, boundary) - es).days / 365.25)
        yrs_B = max(0.0, (dd - max(es, boundary)).days / 365.25)
        # override yrs_A with data-derived value when salary tool has set it
        if ep.get('yrs_A_data', 0.0) > 0.0:
            yrs_A = ep['yrs_A_data']
        epik_ctx = dict(
            compute=True, exagora=ep["epik_exagora"], epik_rate=ep["epik_rate"],
            s_ep=ep["s_ep"], accrual_A=ep["accrual_A"], c_rate_B=ep["c_rate_B"],
            notional_yield=ep["notional_yield"], annuity_div=ep["annuity_div"],
            penalty_A=ep["penalty_A"], yrs_A=yrs_A, yrs_B=yrs_B, Y=Y,
            extra_abroad=(P if v["totalize"] else 0.0))   # abroad → Τμήμα Α
        sp = _epik_A(epik_ctx, epik_ctx["extra_abroad"])  # baseline (before εξαγορά)
        sp["yrs_A"], sp["yrs_B"] = yrs_A, yrs_B
        v["A"] = sp["A"]

    r = _scn(v, v["sf"], v["N"], E, P, epik_ctx)
    disc, grow = pc.disc_growth(v["npv_mode"], v["i"])
    k_epik = _kepik(v, v["sf"], v["N"], epik_ctx)
    S, B, K = pc.sigma(r["dm_net"], v["sf"], v["N"], v["L"], disc, grow, pc.BUY_RATE,
                       v["upfront"], extra_cost=k_epik)

    # pure baseline (T0 only, NO abroad, NO πλασματικά) for the decomposition
    m_base = pc.replacement_rate(v["T0"]) * v["s"]
    A_base = _epik_A(epik_ctx, 0.0)["A"] if epik_ctx else v["A"]

    tab_calc, tab_sal = st.tabs(["Pension strategy", "Salary ⟨s⟩ tool"])
    with tab_calc:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Σ = B − K (€)", f"{S:,.0f}", "ΣΥΜΦΕΡΕΙ" if S > 0 else "όχι θετικό",
                  delta_color="off")
        c2.metric("ΚΑΘΑΡΟ όφελος εξαγ. (€/mo)", f"{r['dm_net']:,.1f}")
        c3.metric("Εθνική E (€/mo)", f"{E:,.1f}")
        c4.metric("age at D (Y)", f"{Y:.2f}")
        left, right = st.columns([1, 2])
        with left:
            st.code(summary_text(v, r, npd, S, B, K, sp, k_epik, m_base, A_base),
                    language="text")
        with right:
            t1, t2, t3, t4 = st.tabs(["Breakdown", "dm vs N", "Σ vs L", "Σ vs N (at L)"])
            t1.pyplot(fig_breakdown(v, r, E, m_base, A_base))
            t2.pyplot(fig_dm_vs_N(v, E, P, epik_ctx))
            t3.pyplot(fig_sigma_vs_L(v, E, P, disc, grow, epik_ctx))
            t4.pyplot(fig_sigma_vs_N(v, E, P, disc, grow, epik_ctx))
    with tab_sal:
        salary_tab()


if __name__ == "__main__":
    main()
