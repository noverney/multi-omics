"""Analysis: case vs control, the classifier, outliers and cross-platform concordance."""

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from omics.dashboard.data import ARM_COLORS, INK, SERIES, sql, style, table

LABELS = {
    "CRP": "Serum CRP, mg/L (Lab A)",
    "HSCRP": "hs-CRP, mg/L (Lab B)",
    "NPX_CRP": "Olink CRP, NPX",
    "NPX_TNF": "Olink TNF, NPX",
    "NPX_IL6": "Olink IL6, NPX",
    "NPX_IL10": "Olink IL10, NPX",
    "HR": "Heart rate, /min",
    "SYSBP": "Systolic BP, mm[Hg]",
    "WEIGHT": "Weight, kg",
}
MARKER = {"size": 8, "line": {"width": 2, "color": "white"}}  # 2px surface ring

st.title("Analysis")
st.caption("Research view only: participants on hold and assay QC failures are excluded.")
raw = sql("SELECT usubjid, study_id, arm, features FROM research.participant_features")
if raw.empty:
    st.info("No research features yet: run `make simulate`.")
    st.stop()
data = pd.concat([raw.drop(columns="features"), pd.json_normalize(raw.features)], axis=1)

st.subheader("Case vs control classifier (logistic regression, 5-fold CV)")
models = sql("SELECT study_id, auc, n, coefficients::text AS weights FROM research.model_score")
for column, model in zip(st.columns(len(models)), models.itertuples(), strict=True):
    column.metric(f"{model.study_id} · ROC AUC", f"{model.auc:.2f}", help=f"n = {model.n}")
table(models, "Model weights (standardized)")

feature = st.selectbox("Measure", [f for f in LABELS if f in data], format_func=LABELS.get)
order = {"arm": ["CONTROL", "CASE"], "study_id": sorted(data.study_id.unique())}
fig = px.box(
    data, x="study_id", y=feature, color="arm", points="all", color_discrete_map=ARM_COLORS,
    category_orders=order, hover_data=["usubjid"],
)  # fmt: skip
fig.update_traces(marker=MARKER, line={"width": 2})
fig.update_layout(xaxis_title=None, yaxis_title=LABELS[feature], boxgap=0.3)
st.plotly_chart(style(fig, height=380))
table(data[["usubjid", "study_id", "arm", feature]])

left, right = st.columns(2)
with left:
    st.subheader("Outliers within their own arm")
    st.caption("Modified z-score (median/MAD) > 3.5 within study × arm.")
    st.dataframe(sql("SELECT * FROM research.outlier ORDER BY abs(robust_z) DESC"),
                 hide_index=True)  # fmt: skip
with right:
    st.subheader("Same samples, two platforms")
    both = data.dropna(subset=["CRP", "NPX_CRP"]).assign(log2_crp=lambda d: np.log2(d.CRP))
    slope, intercept = np.polyfit(both.log2_crp, both.NPX_CRP, 1)
    r = both.log2_crp.corr(both.NPX_CRP)
    fig = px.scatter(both, x="log2_crp", y="NPX_CRP", hover_data=["usubjid"],
                     color_discrete_sequence=[SERIES])  # fmt: skip
    fig.update_traces(marker=MARKER)
    grid = np.linspace(both.log2_crp.min(), both.log2_crp.max(), 2)
    fit = go.Scatter(x=grid, y=slope * grid + intercept, mode="lines", name=f"fit, r = {r:.2f}",
                     line={"width": 2, "color": INK})  # fmt: skip
    fig.add_trace(fit)
    fig.update_layout(xaxis_title="log2 serum CRP, mg/L (Lab A)", yaxis_title="Olink CRP, NPX")
    st.plotly_chart(style(fig, height=320))
    st.caption("NPX is relative: it tracks log2 CRP but is never converted to mg/L.")
    table(both[["usubjid", "CRP", "log2_crp", "NPX_CRP"]])

st.subheader("Genotype → expression (real data: 1000 Genomes + Geuvadis)")
eqtl = sql("SELECT variant, gene, n, slope, r, p_value FROM research.eqtl ORDER BY p_value")
if eqtl.empty:
    st.info("No eQTL yet: the DNA and RNA labs deliver with `make simulate`.")
    st.stop()
pairs = list(zip(eqtl.variant, eqtl.gene, strict=True))
variant, gene = st.selectbox("Variant · gene", pairs, format_func=" · ".join)
points = sql(
    'SELECT g."USUBJID", g."STRESN" AS dosage, g."STRESC" AS genotype, e."STRESN" AS expression'
    ' FROM api.research_findings g JOIN api.research_findings e USING ("USUBJID")'
    " WHERE g.concept_id = %s AND e.concept_id = %s",
    (f"GT_{variant.upper()}", f"EXPR_{gene}"),
)
chosen = eqtl[(eqtl.variant == variant) & (eqtl.gene == gene)].iloc[0]
tiles = st.columns(3)
tiles[0].metric("Correlation r", f"{chosen.r:.2f}")
tiles[1].metric("p-value", f"{chosen.p_value:.1e}")
tiles[2].metric("Change per ALT allele", f"{chosen.slope:+.1f} nRPKM", help=f"n = {chosen.n}")
genotypes = points.sort_values("dosage").genotype.unique().tolist()
fig = px.box(points, x="genotype", y="expression", points="all", hover_data=["USUBJID"],
             category_orders={"genotype": genotypes}, color_discrete_sequence=[SERIES])  # fmt: skip
fig.update_traces(marker=MARKER, line={"width": 2})
fig.update_layout(xaxis_title=f"{variant} genotype", yaxis_title=f"{gene} expression, nRPKM")
st.plotly_chart(style(fig, height=340))
st.caption("Expression is from lymphoblastoid cells; nRPKM = Geuvadis PEER-normalized RPKM.")
table(eqtl, "All tested variant–gene pairs")
