"""Research computations (pure pandas / scikit-learn): features, outliers, classifier."""

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

MODEL_FEATURES = ["CRP", "NPX_TNF", "NPX_IL6", "NPX_IL10", "HR", "SYSBP"]
OUTLIER_Z = 3.5  # Iglewicz-Hoaglin cut-off for the modified z-score


def wide(long: pd.DataFrame) -> pd.DataFrame:
    """Pivot SDTM rows (USUBJID, concept_id, STRESN, DTC) to the latest value per test."""
    latest = long.sort_values("DTC").groupby(["USUBJID", "concept_id"]).tail(1)
    return latest.pivot(index="USUBJID", columns="concept_id", values="STRESN").astype(float)


def robust_z(features: pd.DataFrame, groups: pd.Series) -> pd.DataFrame:
    """Compute the modified z-score per column within each group: 0.6745 (x - median) / MAD."""
    median = features.groupby(groups).transform("median")
    mad = (features - median).abs().groupby(groups).transform("median").replace(0, np.nan)
    return 0.6745 * (features - median) / mad


def outliers(features: pd.DataFrame, groups: pd.Series) -> pd.DataFrame:
    """Values unusual for their own group (|modified z| > 3.5), one row per finding."""
    z = robust_z(features, groups).stack().rename("robust_z")
    hits = z[z.abs() > OUTLIER_Z].reset_index()
    hits.columns = ["usubjid", "feature", "robust_z"]
    hits["value"] = [features.at[u, f] for u, f in zip(hits.usubjid, hits.feature, strict=True)]
    return hits


def case_control_auc(features: pd.DataFrame, is_case: pd.Series) -> tuple[float, dict]:
    """Cross-validated ROC AUC of a logistic regression (case vs control) and its weights."""
    x = features.reindex(columns=MODEL_FEATURES)
    model = make_pipeline(
        SimpleImputer(strategy="median", keep_empty_features=True),
        StandardScaler(),
        LogisticRegression(max_iter=1000),
    )
    folds = StratifiedKFold(n_splits=min(5, int(is_case.value_counts().min())), shuffle=True,
                            random_state=0)  # fmt: skip
    auc = cross_val_score(model, x, is_case, cv=folds, scoring="roc_auc").mean()
    weights = model.fit(x, is_case)[-1].coef_[0]
    return float(auc), {f: round(float(w), 3) for f, w in zip(MODEL_FEATURES, weights, strict=True)}
