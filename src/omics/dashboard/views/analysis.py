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
