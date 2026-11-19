"""Train and compare a historical baseline and a weekly sales model."""


def _feature_matrix(rows):
    # The date and observed sales identify and label a row. Input values must
    # be available before the week we are predicting starts.
    return [[row["last_week_units"], row["mean_last_4"], row["promotion"]] for row in rows]


def baseline_predict(rows) -> list[float]:
    """Predict each week's sales from the mean of its preceding four weeks."""
    return [float(row["mean_last_4"]) for row in rows]


def fit_model(train_rows):
    """Fit the preprocessing and regression on the training rows together."""
    if not train_rows:
        raise ValueError("يحتاج تدريب النموذج إلى صف واحد على الأقل.")

    from sklearn.linear_model import LinearRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    pipeline = make_pipeline(StandardScaler(), LinearRegression())
    return pipeline.fit(_feature_matrix(train_rows), [row["actual_units"] for row in train_rows])


def model_predict(model, rows) -> list[float]:
    """Predict without fitting and cap negative sales forecasts at zero."""
    if not rows:
        return []
    return [max(0.0, float(value)) for value in model.predict(_feature_matrix(rows))]
