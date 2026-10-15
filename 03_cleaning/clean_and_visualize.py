"""
clean_and_visualize.py
----------------------
Reads machines.db (table: machines), audits data quality, cleans it, and draws charts.

Run (from the project folder that contains machines.db):
    python clean_and_visualize.py
    python clean_and_visualize.py path/to/machines.db     # custom path

Outputs (nothing original is modified):
    machines_final.csv        cleaned table, ready for SQL / Power BI / Streamlit
    cleaning_report.csv       every issue found: what, how many rows, what we did
    visuals/*.png             charts for the presentation
    machines_final.db         copy of your DB + new table `machines_final`
"""
import os, re, sys, shutil, sqlite3
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns

HERE = os.path.dirname(os.path.abspath(__file__))
DB = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "04_database", "machines.db")
OUT_VIS = os.path.join(HERE, "..", "08_visuals")
FINAL_CSV = os.path.join(HERE, "..", "07_data_outputs", "machines_final.csv")
FINAL_DB = os.path.join(HERE, "..", "04_database", "machines_final.db")
REPORT_CSV = os.path.join(HERE, "cleaning_report.csv")
os.makedirs(OUT_VIS, exist_ok=True)

df = pd.read_sql("SELECT * FROM machines", sqlite3.connect(DB))
raw_n = len(df)
report = []   # (issue, rows_affected, action)
def log(issue, n, action): report.append({"issue": issue, "rows_affected": int(n), "action": action})

SPECS = ["x_travel_mm", "y_travel_mm", "z_travel_mm", "max_table_load_kg",
         "machine_weight_kg", "spindle_power_kw", "max_spindle_rpm", "tool_capacity"]

# ---------------------------------------------------------------- AUDIT (before)
missing_before = df.isna().mean().mul(100).round(1).sort_values(ascending=False)

# ---------------------------------------------------------------- CLEANING
# 1) completely empty column
empty_cols = [c for c in df.columns if df[c].isna().mean() > 0.99]
df = df.drop(columns=empty_cols)
log(f"Column(s) {empty_cols} are >99% empty (Brand has only 4 values)", raw_n, "Dropped")

# 2) manufacturer spelling variants (Fanuc/FANUC, Grob/GROB, Hyundai WIA/Hyundai-WIA ...)
key = df["Manufacturer"].str.lower().str.replace(r"[^a-z0-9]", "", regex=True)
canon = df.groupby(key)["Manufacturer"].agg(lambda s: s.value_counts().index[0])
before = df["Manufacturer"].nunique()
changed = (df["Manufacturer"] != key.map(canon)).sum()
df["Manufacturer"] = key.map(canon)
log(f"Manufacturer spelling variants ({before} -> {df['Manufacturer'].nunique()} names)", changed,
    "Merged to the most frequent spelling")

# 3) category names: 'Cnc' -> 'CNC'
cat_fix = df["Category"].str.replace(r"\bCnc\b", "CNC", regex=True)
log("Category written 'Cnc' instead of 'CNC'", (cat_fix != df["Category"]).sum(), "Standardised")
df["Category"] = cat_fix

# 4) duplicate machine names (different URL = different variant, so we keep them but flag)
dup = df.duplicated(["Machine Name", "Manufacturer"], keep=False)
df["is_name_duplicate"] = dup.astype(int)
log("Same Machine Name + Manufacturer appears twice (different URLs, e.g. ANCA FX7)", dup.sum(),
    "Kept (different variants) and flagged in is_name_duplicate")
assert df["URL"].is_unique

# 5) physically implausible weights (a machining centre cannot weigh 8 kg -> unit error at source)
bad_w = df["machine_weight_kg"] < 100
log("machine_weight_kg < 100 kg (unit error at source, e.g. 8 kg)", bad_w.sum(), "Set to missing")
df.loc[bad_w, "machine_weight_kg"] = np.nan

# 6) price: keep estimate vs listed visible; add helpers
df["has_price"] = df["price_usd"].notna().astype(int)
df["price_spread_ratio"] = (df["price_high_usd"] / df["price_low_usd"]).round(2)
n_est = (df["price_type"] == "estimate").sum()
log(f"Prices are mostly ESTIMATES by the website ({n_est} estimate vs "
    f"{(df['price_type']=='listed').sum()} listed)", n_est,
    "Added price_type + has_price. Always label price charts as 'estimated'")
wide = df["price_spread_ratio"] > 5
log("Very wide price ranges (high > 5x low)", wide.sum(), "Kept; flagged via price_spread_ratio")

# 7) spindle taper: 60+ spellings -> family
def taper_family(t):
    if not isinstance(t, str): return np.nan
    u = t.upper()
    for fam, pat in [("HSK", r"HSK"), ("BT", r"\bB?BT\s?-?\d|BT\d"), ("CAT", r"CAT|\bCT\s?\d"),
                     ("ISO / SK", r"ISO|SK\s?\d|DIN|#\s?\d|NO\.?\s?\d"), ("Capto", r"CAPTO|PSC")]:
        if re.search(pat, u): return fam
    return "Other"
df["taper_family"] = df["spindle_taper"].map(taper_family)
log("spindle_taper has many spellings (HSK-A63, HSK 63-A, ...)", df["spindle_taper"].notna().sum(),
    f"Added taper_family ({df['taper_family'].nunique()} groups)")

# 8) outliers: flag, do not delete (huge machines are real)
for c in ["x_travel_mm", "max_spindle_rpm", "max_table_load_kg", "price_usd"]:
    s = np.log10(df[c].dropna()); q1, q3 = s.quantile([.25, .75]); iqr = q3 - q1
    out = df[c].notna() & ((np.log10(df[c]) < q1 - 1.5 * iqr) | (np.log10(df[c]) > q3 + 1.5 * iqr))
    df[f"outlier_{c}"] = out.astype(int)
    log(f"Extreme values in {c} (log-IQR x1.5)", out.sum(), "Kept (large/special machines are real); flagged")

# 9) completeness score -> lets the dashboard filter to well-documented machines
df["spec_completeness"] = df[SPECS].notna().sum(axis=1)
for c in SPECS:
    log(f"{c} missing", df[c].isna().sum(), "Left as NULL (never guessed)")

# 10) coverage warning
log("Only part of the website was scraped (categories in file)", df["Category"].nunique(),
    "See categories chart; website has 19")

df.to_csv(FINAL_CSV, index=False, encoding="utf-8-sig")
pd.DataFrame(report).to_csv(REPORT_CSV, index=False, encoding="utf-8-sig")
shutil.copy(DB, FINAL_DB)
con = sqlite3.connect(FINAL_DB); df.to_sql("machines_final", con, if_exists="replace", index=False); con.close()

# ---------------------------------------------------------------- VISUALS
sns.set_theme(style="whitegrid", font_scale=1.05)
PAL = sns.color_palette("crest", 8)
def save(name): plt.tight_layout(); plt.savefig(f"{OUT_VIS}/{name}.png", dpi=160); plt.close()
fmt_k = lambda v, _: f"${v/1e3:,.0f}K" if v < 1e6 else f"${v/1e6:,.1f}M"

# 1 missing data before cleaning
plt.figure(figsize=(9, 6)); m = missing_before.drop(["Description", "price_low_usd", "price_high_usd", "price_mid_usd", "price_text", "price_type"], errors="ignore").rename({"price_usd": "price (all price_* columns)"})
sns.barplot(x=m.values, y=m.index, color=PAL[3])
for i, v in enumerate(m.values): plt.text(v + .8, i, f"{v}%", va="center", fontsize=9)
plt.title("Data quality: % missing values per column (raw data)"); plt.xlabel("% missing"); plt.ylabel(""); plt.xlim(0, 112)
save("01_missing_values")

# 2 machines per category
plt.figure(figsize=(9, 4.5)); c = df["Category"].value_counts()
sns.barplot(x=c.values, y=c.index, color=PAL[4])
for i, v in enumerate(c.values): plt.text(v + 15, i, f"{v:,}", va="center")
plt.title(f"Machines per category ({len(df):,} machines)"); plt.xlabel("machines"); plt.ylabel("")
save("02_machines_per_category")

# 3 top manufacturers
plt.figure(figsize=(9, 6)); t = df["Manufacturer"].value_counts().head(15)[::-1]
sns.barplot(x=t.values, y=t.index, color=PAL[5])
for i, v in enumerate(t.values): plt.text(v + 1.5, i, str(v), va="center")
plt.title("Top 15 manufacturers by number of machines"); plt.xlabel("machines"); plt.ylabel("")
save("03_top_manufacturers")

p = df[df["price_usd"].notna()]
# 4 price distribution
plt.figure(figsize=(9, 4.8))
sns.histplot(p, x="price_usd", hue="price_type", log_scale=True, bins=40, multiple="stack",
             palette={"estimate": PAL[3], "listed": "#e07b39"})
plt.gca().xaxis.set_major_formatter(plt.FuncFormatter(fmt_k))
plt.title(f"Price distribution (log scale) - {len(p):,} machines with a price"); plt.xlabel("price (USD, midpoint)")
save("04_price_distribution")

# 5 median price by category
plt.figure(figsize=(9, 4.5)); g = p.groupby("Category")["price_usd"].agg(["median", "count"]).sort_values("median")
sns.barplot(x=g["median"], y=g.index, color=PAL[5])
for i, (v, n) in enumerate(zip(g["median"], g["count"])): plt.text(v * 1.01, i, f"${v/1e3:,.0f}K  (n={n})", va="center", fontsize=9)
plt.xlim(0, g["median"].max() * 1.3); plt.gca().xaxis.set_major_formatter(plt.FuncFormatter(fmt_k))
plt.title("Median ESTIMATED price by category"); plt.xlabel("median price (USD)"); plt.ylabel("")
save("05_median_price_by_category")

# 6 price vs weight / travel / tool capacity
cats = sorted(df["Category"].unique()); cpal = dict(zip(cats, sns.color_palette("tab10", len(cats))))
fig, ax = plt.subplots(1, 3, figsize=(15, 5.2))
for a, (col, lab) in zip(ax, [("machine_weight_kg", "Machine weight (kg)"), ("x_travel_mm", "X travel (mm)"),
                              ("tool_capacity", "Tool capacity (tools)")]):
    d = p.dropna(subset=[col]); r = np.log10(d[col]).corr(np.log10(d["price_usd"]), method="spearman")
    sns.scatterplot(data=d, x=col, y="price_usd", hue="Category", hue_order=cats, palette=cpal, s=22, alpha=.6, ax=a, legend=False)
    a.set_xscale("log"); a.set_yscale("log"); a.set_xlabel(lab); a.set_ylabel("estimated price (USD)" if a is ax[0] else "")
    a.set_title(f"rho = {r:.2f}  (n={len(d):,})")
handles = [plt.Line2D([], [], marker="o", ls="", color=cpal[c], label=c) for c in cats]
fig.legend(handles=handles, loc="lower center", ncol=len(cats), fontsize=9, frameon=False)
fig.suptitle("What drives price? Bigger / heavier machines cost more (log-log)", fontsize=14)
plt.tight_layout(rect=(0, 0.06, 1, 0.95)); plt.savefig(f"{OUT_VIS}/06_price_vs_size.png", dpi=160); plt.close()

# 7 manufacturers by median price (>=15 priced machines)
q = p.groupby("Manufacturer")["price_usd"].agg(["median", "count"]); q = q[q["count"] >= 15].sort_values("median")
plt.figure(figsize=(9, 6)); sns.barplot(x=q["median"], y=q.index, color=PAL[6])
plt.gca().xaxis.set_major_formatter(plt.FuncFormatter(fmt_k))
plt.title("Median estimated price by manufacturer (15+ priced machines)"); plt.xlabel("USD"); plt.ylabel("")
save("07_price_by_manufacturer")

# 8 spec correlation heatmap (log)
cols = ["price_usd"] + SPECS
lg = df[cols].apply(np.log10); plt.figure(figsize=(8, 6.5))
sns.heatmap(lg.corr(method="spearman"), annot=True, fmt=".2f", cmap="crest", vmin=0, vmax=1, square=True)
plt.title("Spearman correlation between specs (log scale)"); save("08_correlation_heatmap")

# 9 taper family
plt.figure(figsize=(7, 4)); tf = df["taper_family"].value_counts()
sns.barplot(x=tf.index, y=tf.values, color=PAL[4]); plt.title("Spindle taper families"); plt.ylabel("machines"); plt.xlabel("")
save("09_taper_families")

# 10 spec completeness
plt.figure(figsize=(8, 4)); sc = df["spec_completeness"].value_counts().sort_index()
sns.barplot(x=sc.index, y=sc.values, color=PAL[3]); plt.title("How many of the 8 key specs does each machine have?")
plt.xlabel("number of specs available"); plt.ylabel("machines"); save("10_spec_completeness")

print(f"raw rows: {raw_n:,} | final rows: {len(df):,} | columns: {df.shape[1]}")
print(pd.DataFrame(report).to_string(index=False, max_colwidth=70))
print(f"\nSaved: machines_final.csv, cleaning_report.csv, machines_final.db, {OUT_VIS}/ (10 charts)")
