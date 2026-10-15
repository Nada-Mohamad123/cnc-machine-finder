"""
CNC Machine Tools - Machine Finder (Streamlit dashboard)

Run from anywhere:
    streamlit run 09_dashboard/app.py

Input: 07_data_outputs/machines_final.csv (found automatically).
Prices come from machinetoolindex.com. Most of them are the site's own estimates, not quotes.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

HERE = Path(__file__).resolve().parent
CSV = HERE.parent / "07_data_outputs" / "machines_final.csv"

BLUE, ORANGE, NEUTRAL = "#2a78d6", "#eb6834", "#c9c8c2"
INK, INK_2, GRID = "#0b0b0b", "#52514e", "#e7e6e1"

def _stretch():
    """st.plotly_chart / st.dataframe: new Streamlit uses width='stretch', older uses use_container_width."""
    try:
        major, minor = (int(x) for x in st.__version__.split(".")[:2])
        return {"width": "stretch"} if (major, minor) >= (1, 50) else {"use_container_width": True}
    except Exception:
        return {"use_container_width": True}


STRETCH = _stretch()

st.set_page_config(page_title="CNC Machine Finder", page_icon="⚙️", layout="wide")

st.markdown(
    """
    <style>
    .block-container {padding-top: 2rem; max-width: 1300px;}
    div[data-testid="stMetricValue"] {font-size: 1.7rem;}
    </style>
    """,
    unsafe_allow_html=True,
)


# ----------------------------------------------------------------- data
@st.cache_data(show_spinner=False)
def load() -> pd.DataFrame:
    df = pd.read_csv(CSV, low_memory=False)
    df = df.rename(columns={"Machine Name": "machine", "Manufacturer": "manufacturer",
                            "Category": "category", "URL": "url"})
    df["price_type"] = df["price_type"].fillna("no price")
    return df


try:
    data = load()
except FileNotFoundError:
    st.error(f"Data file not found: {CSV}. Keep the project folder structure unchanged.")
    st.stop()

SPEC_LABELS = {
    "x_travel_mm": "X travel (mm)",
    "y_travel_mm": "Y travel (mm)",
    "z_travel_mm": "Z travel (mm)",
    "machine_weight_kg": "Machine weight (kg)",
    "spindle_power_kw": "Spindle power (kW)",
    "max_spindle_rpm": "Max spindle speed (rpm)",
    "max_table_load_kg": "Max table load (kg)",
    "tool_capacity": "Tool capacity (tools)",
}


def money(v) -> str:
    if pd.isna(v):
        return "-"
    return f"${v/1e6:.2f}M" if v >= 1e6 else f"${v/1e3:,.0f}K"


def style(fig, height=380):
    fig.update_layout(
        template="plotly_white", height=height, margin=dict(l=10, r=10, t=40, b=10),
        font=dict(color=INK_2, size=13), paper_bgcolor="white", plot_bgcolor="white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, title_text=""),
        hoverlabel=dict(bgcolor="white", font_color=INK),
    )
    fig.update_xaxes(gridcolor=GRID, zeroline=False, linecolor=GRID)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, linecolor=GRID)
    return fig


# ------------------------------------------------------------- sidebar
st.sidebar.header("Your requirements")
cats = sorted(data["category"].unique())
sel_cats = st.sidebar.multiselect("Category", cats, default=cats)

priced = data[data["has_price"] == 1]
pmax = float(priced["price_mid_usd"].max())
top_k = int(-(-pmax // 25_000) * 25)          # slider maximum in $K
budget_k = st.sidebar.slider("Budget (USD thousands, price midpoint)", 0, top_k, (0, top_k), step=25, format="$%dK")
budget = (budget_k[0] * 1000, budget_k[1] * 1000)
price_choice = st.sidebar.radio(
    "Machines without a price", ["Hide them", "Show them"], index=0,
    help="60% of machines have no price on the website. Hide them for a budget search.",
)
price_types = st.sidebar.multiselect(
    "Price type", ["estimate", "listed"], default=["estimate", "listed"],
    help="'listed' = price published by the manufacturer. 'estimate' = machinetoolindex.com's own estimate.",
)

with st.sidebar.expander("Minimum machine size", expanded=False):
    min_x = st.number_input("Min X travel (mm)", 0, 20000, 0, step=100)
    min_y = st.number_input("Min Y travel (mm)", 0, 10000, 0, step=100)
    min_z = st.number_input("Min Z travel (mm)", 0, 5000, 0, step=100)
    min_kw = st.number_input("Min spindle power (kW)", 0, 300, 0, step=5)

mfrs = sorted(data["manufacturer"].dropna().unique())
sel_mfrs = st.sidebar.multiselect("Manufacturer (optional)", mfrs, default=[])
excl_out = st.sidebar.checkbox(
    "Exclude price outliers in charts", value=False,
    help="26 machines with extreme prices are flagged in the cleaning step. Tick to leave them out of the charts (they stay in the data).",
)

# --------------------------------------------------------------- filter
f = data[data["category"].isin(sel_cats)]
if sel_mfrs:
    f = f[f["manufacturer"].isin(sel_mfrs)]

has_p = f["has_price"] == 1
in_budget = has_p & f["price_mid_usd"].between(budget[0], budget[1]) & f["price_type"].isin(price_types)
f = f[in_budget] if price_choice == "Hide them" else f[in_budget | ~has_p]


def at_least(frame, col, v):
    # A machine with an unknown value is kept only when no minimum is requested.
    return frame if v <= 0 else frame[frame[col] >= v]


for col, v in (("x_travel_mm", min_x), ("y_travel_mm", min_y), ("z_travel_mm", min_z), ("spindle_power_kw", min_kw)):
    f = at_least(f, col, v)

fc = f[f["outlier_price_usd"] == 0] if excl_out else f  # frame used for charts

# --------------------------------------------------------------- header
st.title("CNC Machine Finder")
st.caption(
    "Choose a machine by budget and size. Data: 3,955 machines from machinetoolindex.com "
    f"({data['category'].nunique()} of 19 website categories, {data['manufacturer'].nunique()} manufacturers)."
)

fp = f[f["has_price"] == 1]
k1, k2, k3, k4 = st.columns(4)
k1.metric("Machines match", f"{len(f):,}")
k2.metric("With a price", f"{len(fp):,}")
k3.metric("Median price", money(fp["price_mid_usd"].median()) if len(fp) else "-")
k4.metric("Manufacturers", f"{f['manufacturer'].nunique():,}")

n_priced = int(priced.shape[0])
n_est = int((priced["price_type"] == "estimate").sum())
st.info(
    f"**Read prices with care.** {n_est:,} of {n_priced:,} priced machines ({n_est / n_priced:.0%}) have an "
    "estimated price from the website, not a quote from the manufacturer. Use them to compare and shortlist, "
    "then ask suppliers for a real quotation."
)

if f.empty:
    st.warning("No machine matches these filters. Widen the budget or lower the minimum size.")
    st.stop()

tab_find, tab_market, tab_size, tab_quality = st.tabs(
    ["Machine Finder", "Market overview", "Price vs size", "Data quality"]
)

# ------------------------------------------------------------ tab 1
with tab_find:
    st.subheader("Shortlist")
    sort_by = st.selectbox(
        "Rank by",
        ["Most complete specs", "Closest to my budget (from below)", "Lowest price", "Highest price",
         "Largest X travel", "Most powerful spindle"],
        help="Set the budget slider on the left first. 'Closest to my budget' lists the best machine you can afford.",
    )
    top_n = st.slider("Rows to show", 10, 200, 50, step=10)

    t = f.copy()
    if sort_by.startswith("Closest"):
        t["_k"] = (t["price_mid_usd"] - budget[1]).abs()
        t = t.sort_values(["_k", "spec_completeness"], ascending=[True, False], na_position="last")
    elif sort_by == "Lowest price":
        t = t.sort_values("price_mid_usd", na_position="last")
    elif sort_by == "Highest price":
        t = t.sort_values("price_mid_usd", ascending=False, na_position="last")
    elif sort_by == "Largest X travel":
        t = t.sort_values("x_travel_mm", ascending=False, na_position="last")
    elif sort_by == "Most powerful spindle":
        t = t.sort_values("spindle_power_kw", ascending=False, na_position="last")
    else:
        t = t.sort_values("spec_completeness", ascending=False)
    t = t.head(top_n)

    t = t.assign(price_low_k=t["price_low_usd"] / 1000, price_high_k=t["price_high_usd"] / 1000)
    show = t[["machine", "manufacturer", "category", "price_low_k", "price_high_k", "price_type",
              "x_travel_mm", "y_travel_mm", "z_travel_mm", "machine_weight_kg", "spindle_power_kw",
              "max_spindle_rpm", "spec_completeness", "url"]]
    st.dataframe(
        show, hide_index=True, **STRETCH, height=520,
        column_config={
            "machine": "Machine", "manufacturer": "Manufacturer", "category": "Category",
            "price_low_k": st.column_config.NumberColumn("Price low", format="$%dK"),
            "price_high_k": st.column_config.NumberColumn("Price high", format="$%dK"),
            "price_type": "Price type",
            "x_travel_mm": st.column_config.NumberColumn("X mm", format="%d"),
            "y_travel_mm": st.column_config.NumberColumn("Y mm", format="%d"),
            "z_travel_mm": st.column_config.NumberColumn("Z mm", format="%d"),
            "machine_weight_kg": st.column_config.NumberColumn("Weight kg", format="%d"),
            "spindle_power_kw": st.column_config.NumberColumn("Power kW", format="%.1f"),
            "max_spindle_rpm": st.column_config.NumberColumn("Max rpm", format="%d"),
            "spec_completeness": st.column_config.ProgressColumn("Specs known", min_value=0, max_value=8, format="%d / 8"),
            "url": st.column_config.LinkColumn("Source", display_text="open"),
        },
    )
    st.download_button("Download this shortlist (CSV)", show.to_csv(index=False).encode("utf-8-sig"),
                       "shortlist.csv", "text/csv")
    st.caption("Prices in thousands of US dollars (K). Empty cells mean the website does not publish that value; "
               "missing values are never guessed.")

# ------------------------------------------------------------ tab 2
with tab_market:
    cp = fc[fc["has_price"] == 1]
    if cp.empty:
        st.info("No priced machines in the current selection.")
    else:
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Median price by category")
            g = (cp.groupby("category")["price_mid_usd"].agg(median="median", n="count").reset_index()
                 .sort_values("median"))
            g["label"] = g["median"].map(money)
            fig = px.bar(g, x="median", y="category", orientation="h", text="label", custom_data=["n"],
                         color_discrete_sequence=[BLUE])
            fig.update_traces(textposition="outside", cliponaxis=False,
                              hovertemplate="%{y}<br>Median: %{text}<br>Machines with price: %{customdata[0]}<extra></extra>")
            fig.update_xaxes(title="Median price (USD)", tickprefix="$", tickformat=",.0f", range=[0, g["median"].max() * 1.25])
            fig.update_yaxes(title="")
            st.plotly_chart(style(fig, 360), **STRETCH, theme=None)
        with c2:
            st.subheader("How prices are distributed")
            lg = np.log10(cp["price_mid_usd"].clip(lower=1))
            counts, edges = np.histogram(lg, bins=30)
            centers, widths = (edges[:-1] + edges[1:]) / 2, np.diff(edges)
            lo_p, hi_p = 10 ** edges[:-1], 10 ** edges[1:]
            fig = go.Figure(go.Bar(
                x=centers, y=counts, width=widths * 0.92, marker_color=BLUE,
                customdata=np.stack([lo_p / 1000, hi_p / 1000], axis=1),
                hovertemplate="$%{customdata[0]:,.0f}K to $%{customdata[1]:,.0f}K<br>Machines: %{y}<extra></extra>"))
            ticks = [v for v in (3e4, 1e5, 3e5, 1e6, 3e6, 1e7) if edges[0] - 0.3 <= np.log10(v) <= edges[-1] + 0.3]
            fig.update_xaxes(title="Price midpoint (USD, log scale)", tickvals=[np.log10(v) for v in ticks],
                             ticktext=[money(v) for v in ticks])
            fig.update_yaxes(title="Machines")
            st.plotly_chart(style(fig, 360), **STRETCH, theme=None)
            note = (f"Median {money(cp['price_mid_usd'].median())}, mean {money(cp['price_mid_usd'].mean())}. "
                    "A few very expensive machines pull the mean above the median.")
            st.caption(note.replace("$", "\\$"))

        c3, c4 = st.columns(2)
        with c3:
            st.subheader("Machines per manufacturer (top 12)")
            m = f["manufacturer"].value_counts().head(12).sort_values().reset_index()
            m.columns = ["manufacturer", "machines"]
            fig = px.bar(m, x="machines", y="manufacturer", orientation="h", text="machines",
                         color_discrete_sequence=[BLUE])
            fig.update_traces(textposition="outside", cliponaxis=False,
                              hovertemplate="%{y}: %{x} machines<extra></extra>")
            fig.update_xaxes(title="Machines"); fig.update_yaxes(title="")
            st.plotly_chart(style(fig, 420), **STRETCH, theme=None)
        with c4:
            st.subheader("Median price by manufacturer (5+ priced machines)")
            mm = (cp.groupby("manufacturer")["price_mid_usd"].agg(median="median", n="count").reset_index())
            mm = mm[mm["n"] >= 5].sort_values("median").tail(12)
            if mm.empty:
                st.info("Not enough priced machines per manufacturer in this selection.")
            else:
                mm["label"] = mm["median"].map(money)
                fig = px.bar(mm, x="median", y="manufacturer", orientation="h", text="label", custom_data=["n"],
                             color_discrete_sequence=[BLUE])
                fig.update_traces(textposition="outside", cliponaxis=False,
                                  hovertemplate="%{y}<br>Median: %{text}<br>Priced machines: %{customdata[0]}<extra></extra>")
                fig.update_xaxes(title="Median price (USD)", tickprefix="$", tickformat=",.0f", range=[0, mm["median"].max() * 1.25])
                fig.update_yaxes(title="")
                st.plotly_chart(style(fig, 420), **STRETCH, theme=None)

# ------------------------------------------------------------ tab 3
with tab_size:
    st.subheader("Does a bigger machine cost more?")
    xcol = st.selectbox("Size or performance measure", list(SPEC_LABELS), format_func=SPEC_LABELS.get)
    sp = fc[(fc["has_price"] == 1) & fc[xcol].notna() & (fc[xcol] > 0)]
    if len(sp) < 5:
        st.info("Not enough machines with both a price and this value in the current selection.")
    else:
        rho = sp[[xcol, "price_mid_usd"]].corr("spearman").iloc[0, 1]
        st.markdown(f"Rank correlation (Spearman) between **{SPEC_LABELS[xcol]}** and price: **{rho:.2f}** "
                    f"on {len(sp):,} machines. Closer to 1 means price rises steadily with this measure.")
        sp = sp.copy()
        sp["panel"] = sp["category"]
        fig = px.scatter(sp, x=xcol, y="price_mid_usd", color="price_type", facet_col="panel", facet_col_wrap=3,
                         log_x=True, log_y=True, opacity=0.7,
                         color_discrete_map={"estimate": BLUE, "listed": ORANGE},
                         category_orders={"price_type": ["estimate", "listed"]},
                         hover_data={"machine": True, "manufacturer": True, "panel": False})
        fig.update_traces(marker=dict(size=7, line=dict(width=1, color="white")))
        fig.for_each_annotation(lambda a: a.update(text=a.text.replace("panel=", ""), font=dict(color=INK, size=13)))
        yt = [5e4, 1e5, 2e5, 5e5, 1e6, 2e6, 5e6, 1e7]
        fig.update_xaxes(title="", tickformat="~s")
        fig.update_yaxes(title="", tickvals=yt, ticktext=[money(v) for v in yt], range=[np.log10(4e4), np.log10(1.5e7)])
        fig.add_annotation(text=f"{SPEC_LABELS[xcol]} (log scale)", xref="paper", yref="paper", x=0.5, y=-0.09,
                           showarrow=False, font=dict(color=INK_2))
        fig.add_annotation(text="Price, USD (log scale)", xref="paper", yref="paper", x=-0.085, y=0.5,
                           textangle=-90, showarrow=False, font=dict(color=INK_2))
        fig = style(fig, 680)
        fig.update_layout(margin=dict(l=95, r=10, t=40, b=50))
        st.plotly_chart(fig, **STRETCH, theme=None)
        st.caption("Blue = website estimate, orange = price listed by the manufacturer. Each dot is one machine.")

# ------------------------------------------------------------ tab 4
with tab_quality:
    q1, q2 = st.columns(2)
    with q1:
        st.subheader("How complete is each spec?")
        comp = (f[list(SPEC_LABELS)].notna().mean() * 100).rename(index=SPEC_LABELS).sort_values().reset_index()
        comp.columns = ["spec", "pct"]
        fig = px.bar(comp, x="pct", y="spec", orientation="h", text=comp["pct"].map(lambda v: f"{v:.0f}%"),
                     color_discrete_sequence=[BLUE])
        fig.update_traces(textposition="outside", cliponaxis=False, hovertemplate="%{y}: %{x:.1f}% known<extra></extra>")
        fig.update_xaxes(title="Machines with a value (%)", range=[0, 110])
        fig.update_yaxes(title="")
        st.plotly_chart(style(fig, 380), **STRETCH, theme=None)
    with q2:
        st.subheader("Price coverage by category")
        cov = (data[data["category"].isin(sel_cats)].groupby(["category", "price_type"]).size()
               .unstack(fill_value=0).reindex(columns=["estimate", "listed", "no price"], fill_value=0))
        cov = cov.div(cov.sum(axis=1), axis=0) * 100
        fig = go.Figure()
        for col, color, name in (("estimate", BLUE, "Estimated price"), ("listed", ORANGE, "Listed price"),
                                 ("no price", NEUTRAL, "No price")):
            fig.add_bar(y=cov.index, x=cov[col], orientation="h", name=name, marker=dict(color=color, line=dict(width=1.5, color="white")),
                        hovertemplate="%{y}<br>" + name + ": %{x:.0f}%<extra></extra>")
        fig.update_layout(barmode="stack")
        fig.update_xaxes(title="Share of machines (%)", range=[0, 100])
        fig.update_yaxes(title="", autorange="reversed")
        st.plotly_chart(style(fig, 380), **STRETCH, theme=None)
    st.markdown(
        "**Limits of this data**\n"
        "- Only 6 of the 19 website categories were collected, so results apply to these categories.\n"
        "- Missing specs and prices are left empty and are never guessed.\n"
        "- Price outliers (26 machines) are flagged, not deleted. Turn the sidebar option off to include them."
    )
