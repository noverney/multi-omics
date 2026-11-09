"""Research computations: latest-value pivot, within-group outliers, case/control model."""

import numpy as np
import pandas as pd

from omics.research import MODEL_FEATURES, case_control_auc, outliers, wide


def test_wide_keeps_the_latest_value_per_test():
    long = pd.DataFrame(
        {
            "USUBJID": ["S-P1", "S-P1", "S-P2"],
            "concept_id": ["HSCRP", "HSCRP", "HSCRP"],
            "STRESN": [2.1, 2.4, 1.0],
            "DTC": ["2026-03-01", "2026-03-24", "2026-03-02"],
        }
    )
    assert wide(long).loc["S-P1", "HSCRP"] == 2.4


def test_outliers_are_judged_within_their_own_arm():
    values = [1.0, 1.1, 0.9, 1.2, 1.0, 9.0] + [5.0, 5.2, 4.9, 5.1, 5.0, 5.3]
    people = [f"P{i}" for i in range(12)]
    features = pd.DataFrame({"CRP": values}, index=people)
    arms = pd.Series(["CONTROL"] * 6 + ["CASE"] * 6, index=people)
    hits = outliers(features, arms)
    assert hits.usubjid.tolist() == ["P5"]  # the cases are higher, but not outliers


def test_classifier_separates_cases_from_controls():
    rng = np.random.default_rng(0)
    is_case = pd.Series([True] * 10 + [False] * 10)
    features = pd.DataFrame(
        {f: rng.normal(0, 1, 20) + 2.0 * is_case.to_numpy() for f in MODEL_FEATURES}
    )
    auc, weights = case_control_auc(features, is_case)
    assert auc > 0.9 and set(weights) == set(MODEL_FEATURES)
