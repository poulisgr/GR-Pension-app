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

import pension_core as pc
import salary_engine as se

ACCENT, C_NET, C_NEG, C_GRID = "#1a4f8b", "#2e8b57", "#b22222", "#d0d5da"
BLUE, ORANGE = "#17a2b8", "#e67e22"
SF_COLORS = ["#1a4f8b", "#2e8b57", "#c77d00", "#8e44ad", "#17a2b8", "#b22222"]

st.set_page_config(page_title="Greek Pension Strategy", layout="wide")
st.session_state.setdefault("s_box", 3000.0)


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
    A = sb.number_input("A — επικουρική (€/mo)", value=300.0, step=50.0)
    i = sb.number_input("i — inflation / discount", value=0.02, step=0.005, format="%.3f")
    dsf = sb.number_input("Δsf — step for sf-curve family (€)", value=200.0, step=50.0)

    sb.subheader("Abroad")
    X = sb.number_input("X — total years abroad", value=0.0, step=1.0)
    EU = sb.number_input("EU — thereof pensionable in EU", value=0.0, step=1.0)
    NEU = sb.number_input("NEU — thereof pensionable non-EU", value=0.0, step=1.0)
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
                upfront=0.02 if pay_upfront else 0.0)


# ----------------------------------------------------------------------------
#  Summary (Greek)
# ----------------------------------------------------------------------------
def summary_text(v, r, npd, S, B, K):
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
        sep, "ΑΝΤΑΠΟΔΟΤΙΚΗ ΣΥΝΤΑΞΗ",
        f"  m  (πριν)  = {r['m']:>8.1f}  €/mo",
        f"  m' (μετά)  = {r['mp']:>8.1f}  €/mo",
        sep, "ΔΙΑΦΟΡΑ ΣΥΝΤΑΞΗΣ ΑΠΟ ΕΞΑΓΟΡΑ",
        f"  μικτή   dm (m'-m) = {r['dm_gross']:>7.2f}  €/mo",
        f"  ΚΑΘΑΡΗ  dm        = {r['dm_net']:>7.2f}  €/mo",
        sep, "ΚΡΑΤΗΣΕΙΣ ΒΑΣΗΣ (πριν)",
        f"  Υγεία 6% = {b['health']:>7.1f}   ΕΑΣ = {b['eas']:>6.1f}",
        f"  Φόρος    = {b['tax']:>7.1f}",
        f"  καθαρή σύνταξη πριν = {b['net']:>8.1f}  €/mo",
        f"  καθαρή σύνταξη μετά = {a['net']:>8.1f}  €/mo",
        sep, "ΑΞΙΟΛΟΓΗΣΗ ΕΞΑΓΟΡΑΣ",
        f"  K  κόστος εξαγοράς      = {K:>9.1f} €",
        f"  B  παρούσα αξία οφέλους = {B:>9.1f} €",
        f"  Σ = B - K               = {S:>9.1f} €",
        "  → ΣΥΜΦΕΡΕΙ" if S > 0 else "  → όχι ακόμα θετικό",
    ]
    return "\n".join(lines)


# ----------------------------------------------------------------------------
#  Charts
# ----------------------------------------------------------------------------
def _scn(v, sf, N, E, P):
    return pc.scenario(v["T0"], v["s"], sf, N, E, v["A"], pc.CHILDREN, pc.EAS_MAIN,
                       v["eas_mode"], pc.HEALTH_RATE, v["eas_on_epik"], P)


def fig_breakdown(v, r, E):
    b, a = r["before"], r["after"]
    base_h, base_e, base_t = b["health"], b["eas"], b["tax"]
    steps = [("E\nΕθνική", v["E_nat"] if False else E, C_NET), ("A\nΕπικ.", v["A"], C_NET),
             ("m\nΑνταπ.", r["m"], C_NET), ("dm\n(μικτό)", r["dm_gross"], BLUE),
             ("Υγεία6%\nβάση", -base_h, C_NEG), ("ΕΑΣ\nβάση", -base_e, C_NEG),
             ("Φόρος\nβάση", -base_t, C_NEG),
             ("ΔΥγεία", -(a["health"]-base_h), ORANGE), ("ΔΕΑΣ", -(a["eas"]-base_e), ORANGE),
             ("ΔΦόρος", -(a["tax"]-base_t), ORANGE)]
    labels = [s[0] for s in steps] + ["NET\n(μετά)"]
    fig = Figure(figsize=(7.6, 5.2)); ax = fig.add_subplot(111)
    ymax = E + v["A"] + r["mp"]; ith = 0.055 * ymax; cum = 0.0
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
    ax.axhline(b["net"], color="#888", lw=1, ls=":", label=f"NET πριν = {b['net']:.0f}")
    ax.axhline(0, color="#333", lw=.8)
    ax.set_xticks(range(len(labels))); ax.set_xticklabels(labels, rotation=20, fontsize=7)
    ax.set_ylim(0, 3500); ax.set_ylabel("€ / month"); ax.legend(fontsize=8)
    ax.set_title("Waterfall καθαρής σύνταξης"); ax.grid(axis="y", color=C_GRID, lw=.6)
    fig.tight_layout(); return fig


def fig_dm_vs_N(v, E, P):
    Ns = list(range(0, pc.MAX_N + 1))
    g = [_scn(v, v["sf"], n, E, P)["dm_gross"] for n in Ns]
    nt = [_scn(v, v["sf"], n, E, P)["dm_net"] for n in Ns]
    fig = Figure(figsize=(7.6, 5.2)); ax = fig.add_subplot(111)
    ax.plot(Ns, g, "o-", color=ACCENT, label="μικτό dm")
    ax.plot(Ns, nt, "s-", color=C_NET, label="ΚΑΘΑΡΟ dm")
    ax.axvline(v["N"], color=C_NEG, ls="--", lw=1, label=f"N={v['N']}")
    ax.set_xticks(Ns); ax.set_ylim(0, 500); ax.set_xlabel("N"); ax.set_ylabel("Δ σύνταξη €/mo")
    ax.set_title("Διαφορά σύνταξης vs N"); ax.legend(); ax.grid(color=C_GRID, lw=.6)
    fig.tight_layout(); return fig


def fig_sigma_vs_L(v, E, P, disc, grow):
    Ls = list(range(0, 26)); fig = Figure(figsize=(7.6, 5.2)); ax = fig.add_subplot(111)
    for k, col in zip(range(6), SF_COLORS):
        sf = v["sf"] + k * v["dsf"]; rr = _scn(v, sf, v["N"], E, P)
        Ss = [pc.sigma(rr["dm_net"], sf, v["N"], L, disc, grow, pc.BUY_RATE, v["upfront"])[0]
              for L in Ls]
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


def fig_sigma_vs_N(v, E, P, disc, grow):
    Ns = list(range(1, pc.MAX_N + 1)); fig = Figure(figsize=(7.6, 5.2)); ax = fig.add_subplot(111)
    for k, col in zip(range(6), SF_COLORS):
        sf = v["sf"] + k * v["dsf"]
        Ss = [pc.sigma(_scn(v, sf, n, E, P)["dm_net"], sf, n, v["L"], disc, grow,
                       pc.BUY_RATE, v["upfront"])[0] for n in Ns]
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
    sal_pdf = c1.file_uploader("EFKA earnings PDF", type="pdf")
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
            if sal_pdf is not None:
                tf = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
                tf.write(sal_pdf.read()); tf.close()
                rows = se.parse_efka(tf.name); os.unlink(tf.name); srcname = sal_pdf.name
            else:
                rows = se.SAMPLE; srcname = "built-in SAMPLE (2007–2009)"
            s_val, months, days, num, aug, skipped = se.compute_average_salary(
                rows, cpi, insured, int(start_year))
            st.session_state["last_s"] = s_val
            st.success(f"⟨s⟩ = {s_val:,.2f} €/mo   "
                       f"(source {srcname}; {days:,.0f} days → {months:,.2f} months; "
                       f"CPI: {src}; before {int(start_year)} ignored: {skipped})")
        except SystemExit as e:
            st.error(str(e))
        except Exception as e:
            st.error(f"Error: {e}")
    if "last_s" in st.session_state:
        st.button(f"✓ Use ⟨s⟩ = {st.session_state['last_s']:,.2f} in the calculator",
                  on_click=_apply_s)          # callback runs BEFORE widgets rebuild
        if st.session_state.pop("s_copied", False):
            st.success("⟨s⟩ copied to the Simulation input (see the sidebar).")


def _apply_s():
    """on_click callback: push the computed <s> into the sidebar input key."""
    st.session_state["s_box"] = float(round(st.session_state.get("last_s", 0.0), 2))
    st.session_state["s_copied"] = True


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
    r = _scn(v, v["sf"], v["N"], E, P)
    disc, grow = pc.disc_growth(v["npv_mode"], v["i"])
    S, B, K = pc.sigma(r["dm_net"], v["sf"], v["N"], v["L"], disc, grow, pc.BUY_RATE, v["upfront"])

    tab_calc, tab_sal = st.tabs(["Pension strategy", "Salary ⟨s⟩ tool"])
    with tab_calc:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Σ = B − K (€)", f"{S:,.0f}", "ΣΥΜΦΕΡΕΙ" if S > 0 else "όχι θετικό",
                  delta_color="off")
        c2.metric("ΚΑΘΑΡΟ dm (€/mo)", f"{r['dm_net']:,.1f}")
        c3.metric("Εθνική E (€/mo)", f"{E:,.1f}")
        c4.metric("age at D (Y)", f"{Y:.2f}")
        left, right = st.columns([1, 2])
        with left:
            st.code(summary_text(v, r, npd, S, B, K), language="text")
        with right:
            t1, t2, t3, t4 = st.tabs(["Breakdown", "dm vs N", "Σ vs L", "Σ vs N (at L)"])
            t1.pyplot(fig_breakdown(v, r, E))
            t2.pyplot(fig_dm_vs_N(v, E, P))
            t3.pyplot(fig_sigma_vs_L(v, E, P, disc, grow))
            t4.pyplot(fig_sigma_vs_N(v, E, P, disc, grow))
    with tab_sal:
        salary_tab()


if __name__ == "__main__":
    main()
