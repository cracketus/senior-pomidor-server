from tools.evaluate_feature_planner import evaluate_suite


def test_feature_planner_historical_evaluation_passes() -> None:
    summary = evaluate_suite()

    assert summary.case_count == 10
    assert summary.passing_revision_cases >= summary.required_passing_cases
    assert summary.minimum_revision_score >= 16
