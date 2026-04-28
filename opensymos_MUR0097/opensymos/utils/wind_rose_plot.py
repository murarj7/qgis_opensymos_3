import math

import matplotlib.pyplot as plt
import numpy as np


DIRECTION_TO_DEGREES = {
    "s": 0,
    "sv": 45,
    "v": 90,
    "jv": 135,
    "j": 180,
    "jz": 225,
    "z": 270,
    "sz": 315,
}

REQUIRED_COLUMNS_BASE = {"speed", "frequency"}
REQUIRED_COLUMNS_STABILITY = {"speed", "frequency", "stability"}

# SYMOS XML stores only representative speed-class values.
REPRESENTATIVE_SPEED_CLASSES = [1.7, 5.0, 11.0]
REPRESENTATIVE_SPEED_LABELS = [
    "Class 1.7 m/s",
    "Class 5.0 m/s",
    "Class 11.0 m/s",
]
DIRECTION_ANGLES_DEG = np.array([0, 45, 90, 135, 180, 225, 270, 315], dtype=float)
THETA = np.deg2rad(DIRECTION_ANGLES_DEG)
BAR_WIDTH = np.deg2rad(45.0)
DIRECTION_GRID_LABELS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def _validate_columns(df, required_columns):
    """
    Validate that the input DataFrame contains all required columns.
    """
    missing = required_columns - set(df.columns)
    if missing:
        raise KeyError(f"Missing required columns: {', '.join(sorted(missing))}")


def _validate_non_empty(df, message="Input DataFrame is empty."):
    """
    Validate that the input DataFrame is not empty.
    """
    if df.empty:
        raise ValueError(message)


def _to_numeric_array(series, column_name):
    """
    Convert a pandas Series-like object to a NumPy float array.
    """
    try:
        return np.asarray(series, dtype=float)
    except Exception as exc:
        raise ValueError(f"Column '{column_name}' must contain numeric values.") from exc


def _ensure_direction_degrees(df):
    """
    Ensure the DataFrame contains a numeric direction_deg column.
    """
    if "direction_deg" in df.columns:
        result = df.copy()
        result["direction_deg"] = _to_numeric_array(result["direction_deg"], "direction_deg")
        return result

    if "direction" not in df.columns:
        raise KeyError("Missing required column: direction_deg or direction")

    result = df.copy()
    result["direction_deg"] = result["direction"].map(DIRECTION_TO_DEGREES)

    if result["direction_deg"].isna().any():
        bad_values = sorted(result.loc[result["direction_deg"].isna(), "direction"].astype(str).unique())
        raise ValueError(f"Unknown direction codes found: {bad_values}")

    result["direction_deg"] = _to_numeric_array(result["direction_deg"], "direction_deg")
    return result


def _prepare_base_dataframe(df):
    """
    Prepare and validate the DataFrame used for plotting.
    """
    _validate_columns(df, REQUIRED_COLUMNS_BASE)
    _validate_non_empty(df)

    prepared = _ensure_direction_degrees(df.copy())
    prepared["speed"] = _to_numeric_array(prepared["speed"], "speed")
    prepared["frequency"] = _to_numeric_array(prepared["frequency"], "frequency")
    return prepared


def _representative_speed_mask(df, representative_speed, tolerance=1e-9):
    """
    Select rows belonging to one representative SYMOS speed class.
    """
    return np.isclose(df["speed"].to_numpy(dtype=float), float(representative_speed), atol=tolerance)


def _stacked_values_by_direction(df_subset):
    """
    Aggregate weighted frequencies for the 8 coarse direction sectors.
    """
    values = []
    for angle_deg in DIRECTION_ANGLES_DEG:
        total = float(df_subset.loc[df_subset["direction_deg"] == angle_deg, "frequency"].sum())
        values.append(total)
    return np.asarray(values, dtype=float)


def _draw_symos_wind_rose(ax, df_subset, title):
    """
    Draw a SYMOS-consistent wind rose using the 3 representative speed classes
    that are actually present in the XML input.
    """
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)

    cumulative = np.zeros(len(DIRECTION_ANGLES_DEG), dtype=float)
    colors = plt.cm.viridis(np.linspace(0.15, 0.85, len(REPRESENTATIVE_SPEED_CLASSES)))

    for color, representative_speed, label in zip(
        colors,
        REPRESENTATIVE_SPEED_CLASSES,
        REPRESENTATIVE_SPEED_LABELS,
    ):
        class_mask = _representative_speed_mask(df_subset, representative_speed)
        class_subset = df_subset.loc[class_mask]
        values = _stacked_values_by_direction(class_subset)

        ax.bar(
            THETA,
            values,
            width=BAR_WIDTH,
            bottom=cumulative,
            align="center",
            edgecolor="white",
            color=color,
            label=label,
        )
        cumulative += values

    ax.set_title(title, fontsize=14, fontweight="bold", pad=20)
    ax.set_thetagrids(DIRECTION_ANGLES_DEG, labels=DIRECTION_GRID_LABELS)
    ax.legend(title="Representative speed class", loc="lower left", bbox_to_anchor=(0.0, 0.0))


def create_wind_rose(df, title="Wind Rose", figsize=(8, 8), save_path=None):
    """
    Create a SYMOS-consistent wind rose plot from a DataFrame.

    The source XML contains only 3 representative speed classes (1.7, 5.0,
    11.0 m/s), so the plot uses exactly these 3 classes and does not invent
    intermediate speed bins.
    """
    prepared = _prepare_base_dataframe(df)

    fig, ax = plt.subplots(figsize=figsize, subplot_kw={"projection": "polar"})
    _draw_symos_wind_rose(ax, prepared, title)

    if save_path:
        fig.savefig(save_path, dpi=300, bbox_inches="tight")

    return fig, ax


def create_wind_rose_by_stability(df, stability_class, figsize=(8, 8), save_path=None):
    """
    Create a wind rose plot for a specific stability class.
    """
    _validate_columns(df, REQUIRED_COLUMNS_STABILITY)
    _validate_non_empty(df)

    stability_mask = df["stability"].astype(str) == str(stability_class)
    df_filtered = df.loc[stability_mask]

    _validate_non_empty(
        df_filtered,
        message=f"No data found for stability class '{stability_class}'.",
    )

    title = f"Wind Rose - Stability Class {stability_class}"
    return create_wind_rose(df_filtered, title=title, figsize=figsize, save_path=save_path)


def create_combined_wind_rose(df, figsize=(12, 10), save_path=None):
    """
    Create wind rose plots for all stability classes plus one overall plot.
    """
    _validate_columns(df, REQUIRED_COLUMNS_STABILITY)
    _validate_non_empty(df)

    prepared = _prepare_base_dataframe(df)
    prepared["stability"] = df["stability"].astype(str)

    stability_classes = sorted(
        prepared["stability"].unique(),
        key=lambda value: int(value) if str(value).isdigit() else str(value),
    )
    total_plots = len(stability_classes) + 1
    ncols = 3
    nrows = math.ceil(total_plots / ncols)

    fig, axes = plt.subplots(
        nrows,
        ncols,
        figsize=figsize,
        subplot_kw={"projection": "polar"},
    )

    if hasattr(axes, "flatten"):
        axes = axes.flatten()
    else:
        axes = [axes]

    for index, stability_class in enumerate(stability_classes):
        subset = prepared.loc[prepared["stability"] == stability_class]
        _draw_symos_wind_rose(axes[index], subset, f"Class {stability_class}")
        axes[index].legend(loc="lower left", fontsize=8)

    overall_ax = axes[len(stability_classes)]
    _draw_symos_wind_rose(overall_ax, prepared, "Overall")
    overall_ax.legend(loc="lower left", fontsize=8)

    for hidden_index in range(total_plots, len(axes)):
        axes[hidden_index].set_visible(False)

    fig.suptitle("Wind Roses by Stability Class", fontsize=14, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.96])

    if save_path:
        fig.savefig(save_path, dpi=300, bbox_inches="tight")

    return fig, axes
