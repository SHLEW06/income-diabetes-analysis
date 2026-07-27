"""Reproduce the core income and diabetes analysis across annual CHR files."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import statsmodels.formula.api as smf
from scipy import stats


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CSV_FILES = {
    2018: "analytic_data2018_0.csv",
    2019: "analytic_data2019.csv",
    2020: "analytic_data2020_0.csv",
    2021: "analytic_data2021.csv",
    2022: "analytic_data2022.csv",
    2023: "analytic_data2023_0.csv",
    2024: "analytic_data2024.csv",
    2025: "analytic_data2025.csv",
}
RENAME_MAP = {
    "Median Household Income raw value": "median_income",
    "Median household income raw value": "median_income",
    "Diabetes Prevalence raw value": "diabetes_rate",
    "Diabetes prevalence raw value": "diabetes_rate",
    "High School Graduation raw value": "hs_graduation_rate",
    "High school graduation raw value": "hs_graduation_rate",
    "High School Completion raw value": "hs_graduation_rate",
    "High school completion raw value": "hs_graduation_rate",
    "Food Environment Index raw value": "food_env_index",
    "Food environment index raw value": "food_env_index",
}
IDENTIFIER_COLUMNS = (
    "State Abbreviation",
    "Name",
    "5-digit FIPS Code",
    "Release Year",
)
ANALYSIS_COLUMNS = (
    "median_income",
    "diabetes_rate",
    "hs_graduation_rate",
    "food_env_index",
)


def load_annual_data(data_dir: Path) -> pd.DataFrame:
    """Load and harmonize the eight County Health Rankings extracts."""
    source_columns = set(IDENTIFIER_COLUMNS) | set(RENAME_MAP)
    frames = []

    for year, filename in CSV_FILES.items():
        path = data_dir / filename
        frame = pd.read_csv(
            path,
            usecols=lambda column: column in source_columns,
            low_memory=False,
        )
        frame["Year"] = year
        frame = frame.rename(columns=RENAME_MAP)
        frame = frame.loc[:, ~frame.columns.duplicated()]
        frames.append(frame)

    combined = pd.concat(frames, ignore_index=True)
    combined[list(ANALYSIS_COLUMNS)] = combined[list(ANALYSIS_COLUMNS)].apply(
        pd.to_numeric,
        errors="coerce",
    )
    return combined.dropna(subset=list(ANALYSIS_COLUMNS)).reset_index(drop=True)


def remove_outliers_iqr(frame: pd.DataFrame, columns: tuple[str, ...]) -> pd.DataFrame:
    """Remove rows outside 1.5 times the IQR for any selected column."""
    keep = pd.Series(True, index=frame.index)
    for column in columns:
        first_quartile = frame[column].quantile(0.25)
        third_quartile = frame[column].quantile(0.75)
        iqr = third_quartile - first_quartile
        keep &= frame[column].between(
            first_quartile - 1.5 * iqr,
            third_quartile + 1.5 * iqr,
        )
    return frame.loc[keep].copy()


def annual_correlations(frame: pd.DataFrame) -> pd.DataFrame:
    """Calculate the income-diabetes Pearson correlation for each year."""
    rows = []
    for year, annual in frame.groupby("Year", sort=True):
        coefficient, p_value = stats.pearsonr(
            annual["median_income"],
            annual["diabetes_rate"],
        )
        rows.append(
            {
                "year": int(year),
                "observations": len(annual),
                "pearson_r": coefficient,
                "p_value": p_value,
            }
        )
    return pd.DataFrame(rows).set_index("year")


def fit_models(frame: pd.DataFrame) -> tuple[pd.DataFrame, object]:
    """Fit the controlled model separately by year and on the pooled sample."""
    formula = (
        "diabetes_rate ~ median_income + hs_graduation_rate + food_env_index"
    )
    rows = []
    for year, annual in frame.groupby("Year", sort=True):
        model = smf.ols(formula, data=annual).fit()
        rows.append(
            {
                "year": int(year),
                "observations": int(model.nobs),
                "r_squared": model.rsquared,
                "income_coefficient": model.params["median_income"],
                "income_p_value": model.pvalues["median_income"],
            }
        )

    pooled_model = smf.ols(formula, data=frame).fit()
    return pd.DataFrame(rows).set_index("year"), pooled_model


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce the project's core income and diabetes estimates."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=PROJECT_ROOT,
        help="Directory containing the eight checked-in annual CSV files.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    combined = load_annual_data(args.data_dir.resolve())
    cleaned = remove_outliers_iqr(
        combined,
        ("median_income", "diabetes_rate"),
    )
    correlations = annual_correlations(cleaned)
    annual_models, pooled_model = fit_models(cleaned)

    print(
        f"Analysis sample: {len(cleaned):,} county-year observations "
        f"from {cleaned['Year'].nunique()} annual files"
    )
    print("\nAnnual Pearson correlations")
    print(correlations.to_string(float_format=lambda value: f"{value:.6f}"))
    print("\nControlled annual models")
    print(annual_models.to_string(float_format=lambda value: f"{value:.6f}"))

    income_coefficient = pooled_model.params["median_income"]
    effect_per_10k = income_coefficient * 10_000 * 100
    print("\nPooled controlled model")
    print(f"R-squared: {pooled_model.rsquared:.6f}")
    print(f"Income coefficient: {income_coefficient:.10f}")
    print(f"Income p-value: {pooled_model.pvalues['median_income']:.6e}")
    print(
        "Estimated diabetes-prevalence change per $10,000 higher income: "
        f"{effect_per_10k:.4f} percentage points"
    )


if __name__ == "__main__":
    main()
