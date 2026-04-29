import os
from io import BytesIO

import matplotlib
matplotlib.use("Agg")
print(f"[ANALYZER] Matplotlib backend set to: {matplotlib.get_backend()}")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from .xml_parser import parse_wind_rose_xml


DIRECTION_CODES = ["s", "sv", "v", "jv", "j", "jz", "z", "sz"]

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

DIRECTION_TO_NAME = {
    "s": "North",
    "sv": "Northeast",
    "v": "East",
    "jv": "Southeast",
    "j": "South",
    "jz": "Southwest",
    "z": "West",
    "sz": "Northwest",
}

DIRECTION_TO_SHORT_NAME = {
    "s": "North",
    "sv": "NE",
    "v": "East",
    "jv": "SE",
    "j": "South",
    "jz": "SW",
    "z": "West",
    "sz": "NW",
}

REPRESENTATIVE_SPEED_CLASSES = [1.7, 5.0, 11.0]
REPRESENTATIVE_SPEED_LABELS = [
    "Class 1.7 m/s",
    "Class 5.0 m/s",
    "Class 11.0 m/s",
]
DIRECTION_ANGLES_DEG = np.array([0, 45, 90, 135, 180, 225, 270, 315], dtype=float)


def get_direction_degrees(direction_code):
    """
    Convert a direction code to degrees.
    """
    return DIRECTION_TO_DEGREES.get(direction_code, 0)


def get_direction_name(direction_code):
    """
    Convert a direction code to a full English direction name.
    """
    return DIRECTION_TO_NAME.get(direction_code, direction_code)


def get_total_calm_frequency(df):
    """
    Return total calm frequency across all stability classes.

    Calm is repeated in every row of a given stability class, so only the first
    value per class must be used.
    """
    if "calm" not in df.columns or df.empty:
        return 0.0

    return float(df.groupby(df["stability"].astype(str))["calm"].first().sum())


def redistribute_calm_to_first_speed_class(df):
    """
    Replicate original plugin behaviour for analysis/plotting:
    calm frequency is redistributed into the first speed class (1.7 m/s)
    according to directional weights of that class.

    Returns a NEW DataFrame.
    Works correctly both for zero calm and non-zero calm.
    """
    if df.empty or "calm" not in df.columns:
        return df.copy()

    redistributed = df.copy()
    redistributed["stability"] = redistributed["stability"].astype(str)
    redistributed["speed"] = pd.to_numeric(redistributed["speed"], errors="raise")
    redistributed["frequency"] = pd.to_numeric(redistributed["frequency"], errors="raise")
    redistributed["calm"] = pd.to_numeric(redistributed["calm"], errors="raise")

    for stability_class, group in redistributed.groupby("stability"):
        calm_value = float(group["calm"].iloc[0]) if not group.empty else 0.0

        # Nothing to do for zero calm
        if calm_value == 0.0:
            continue

        mask_first_speed = (
            (redistributed["stability"] == stability_class)
            & np.isclose(redistributed["speed"], 1.7, atol=1e-9)
        )
        first_speed_df = redistributed.loc[mask_first_speed]

        if first_speed_df.empty:
            continue

        row_sum = float(first_speed_df["frequency"].sum())

        if row_sum > 0.0:
            for idx in first_speed_df.index:
                value = float(redistributed.at[idx, "frequency"])
                weight = value / row_sum
                redistributed.at[idx, "frequency"] = value + weight * calm_value
        else:
            # Robust fallback: if class 1.7 has no directional frequencies,
            # distribute calm evenly across 8 directions.
            equal_share = calm_value / 8.0
            for idx in first_speed_df.index:
                redistributed.at[idx, "frequency"] = equal_share

    return redistributed


# -------------------------------------------------------------------
# 2. DATA PREPARATION AND VALIDATION
# -------------------------------------------------------------------
def enrich_wind_rose_dataframe(df):
    """
    Add helper columns used by analysis and plotting.
    """
    required_columns = {"stability", "speed", "direction", "frequency", "calm"}
    missing = required_columns - set(df.columns)
    if missing:
        raise KeyError(f"Missing required columns: {', '.join(sorted(missing))}")

    enriched = df.copy()
    enriched["stability"] = enriched["stability"].astype(str)
    enriched["speed"] = pd.to_numeric(enriched["speed"], errors="raise")
    enriched["frequency"] = pd.to_numeric(enriched["frequency"], errors="raise")
    enriched["calm"] = pd.to_numeric(enriched["calm"], errors="raise")
    enriched["direction_deg"] = enriched["direction"].map(get_direction_degrees)
    enriched["direction_name"] = enriched["direction"].map(get_direction_name)

    if enriched["direction_deg"].isna().any():
        bad_values = sorted(enriched.loc[enriched["direction_deg"].isna(), "direction"].unique())
        raise ValueError(f"Unknown direction codes found: {bad_values}")

    return enriched


def calculate_direction_totals(df):
    """
    Calculate total frequency by direction code.
    """
    return {
        direction_code: float(df.loc[df["direction"] == direction_code, "frequency"].sum())
        for direction_code in DIRECTION_CODES
    }


def calculate_class_statistics(df):
    """
    Calculate per-stability-class statistics.
    """
    class_stats = {}

    for stability_class in sorted(df["stability"].astype(str).unique(), key=lambda value: int(value)):
        stability_df = df.loc[df["stability"].astype(str) == stability_class]

        total_frequency = float(stability_df["frequency"].sum())
        direction_totals = calculate_direction_totals(stability_df)

        if direction_totals:
            dominant_direction_code = max(direction_totals, key=direction_totals.get)
            dominant_direction_name = get_direction_name(dominant_direction_code)
            dominant_value = float(direction_totals[dominant_direction_code])
        else:
            dominant_direction_code = "N/A"
            dominant_direction_name = "N/A"
            dominant_value = 0.0

        class_stats[stability_class] = {
            "total_frequency": total_frequency,
            "dominant_dir_code": dominant_direction_code,
            "dominant_dir_name": dominant_direction_name,
            "dominant_value": dominant_value,
            "calm_frequency": float(stability_df["calm"].iloc[0]) if not stability_df.empty else 0.0,
            "speed_range": (
                float(stability_df["speed"].min()) if not stability_df.empty else 0.0,
                float(stability_df["speed"].max()) if not stability_df.empty else 0.0,
            ),
        }

    return class_stats


def calculate_statistics(df):
    """
    Calculate overall wind-rose statistics.

    Direction-based statistics are calculated from a calculation-consistent
    DataFrame where calm is redistributed into the 1.7 m/s class.
    Total calm frequency is kept from the original raw XML data.
    """
    df_plot = redistribute_calm_to_first_speed_class(df)

    direction_totals = calculate_direction_totals(df_plot)

    if direction_totals:
        dominant_direction_code = max(direction_totals, key=direction_totals.get)
        dominant_direction_name = get_direction_name(dominant_direction_code)
        dominant_value = float(direction_totals[dominant_direction_code])
    else:
        dominant_direction_code = "N/A"
        dominant_direction_name = "N/A"
        dominant_value = 0.0

    class_stats = calculate_class_statistics(df_plot)
    available_speed_classes = sorted({float(value) for value in df["speed"].unique()})
    total_calm_frequency = float(
        df.groupby(df["stability"].astype(str))["calm"].first().sum()
    )

    return {
        "total_records": int(len(df)),
        "stability_classes": sorted(df["stability"].astype(str).unique(), key=lambda value: int(value)),
        "speed_range": (float(df["speed"].min()), float(df["speed"].max())),
        "available_speed_classes": available_speed_classes,
        "dominant_direction_code": dominant_direction_code,
        "dominant_direction_name": dominant_direction_name,
        "dominant_value": dominant_value,
        "direction_totals": direction_totals,
        "class_stats": class_stats,
        "total_calm_frequency": total_calm_frequency,
    }


# -------------------------------------------------------------------
# 3. VISUALIZATION
# -------------------------------------------------------------------
def create_simple_direction_plot(df, figsize=(10, 6)):
    """
    Create a bar plot of direction frequencies.

    Calm is redistributed into the 1.7 m/s class exactly like in the original
    plugin calculation, but the original calm total is also shown explicitly.
    """
    df_plot = redistribute_calm_to_first_speed_class(df)
    calm_total = get_total_calm_frequency(df)

    direction_totals = {
        DIRECTION_TO_SHORT_NAME[direction_code]: float(
            df_plot.loc[df_plot["direction"] == direction_code, "frequency"].sum()
        )
        for direction_code in DIRECTION_CODES
    }

    fig, ax = plt.subplots(figsize=figsize)

    directions = list(direction_totals.keys())
    values = list(direction_totals.values())
    colors = plt.cm.viridis(np.linspace(0.2, 0.8, len(directions)))
    bars = ax.bar(directions, values, color=colors, edgecolor="black", alpha=0.8)

    for bar, value in zip(bars, values):
        height = bar.get_height()
        ax.text(
            bar.get_x() + bar.get_width() / 2.0,
            height + 0.1,
            f"{value:.1f}%",
            ha="center",
            va="bottom",
            fontsize=9,
        )

    average_value = float(np.mean(values)) if values else 0.0

    ax.set_title("Wind Direction Frequencies", fontsize=14, fontweight="bold")
    ax.set_xlabel("Wind Direction", fontsize=12)
    ax.set_ylabel("Frequency (%)", fontsize=12)
    ax.grid(True, alpha=0.3, linestyle="--")
    ax.set_axisbelow(True)
    ax.axhline(
        y=average_value,
        color="red",
        linestyle="--",
        alpha=0.5,
        label=f"Average: {average_value:.1f}%",
    )

    calm_note = (
        f"Calm total: {calm_total:.2f}%\n"
        "Calm redistributed to 1.7 m/s class"
        if calm_total > 0.0
        else "Calm total: 0.00%"
    )

    ax.legend(loc="upper left", bbox_to_anchor=(1.02, 1.0), borderaxespad=0.0)

    fig.text(
        0.624, 0.87,
        calm_note,
        ha="left",
        va="top",
        fontsize=9,
        bbox=dict(boxstyle="round", facecolor="white", alpha=0.85, edgecolor="gray"),
    )

    fig.tight_layout(rect=[0, 0.02, 0.80, 1.0])
    return fig


def create_matplotlib_polar_wind_rose(df, figsize=(8, 8)):
    """
    Create a SYMOS-consistent polar wind rose.

    Calm is redistributed into the 1.7 m/s class like in the original plugin.
    The original calm total is shown as an annotation.
    """
    required_columns = {"direction_deg", "speed", "frequency"}
    missing = required_columns - set(df.columns)
    if missing:
        raise KeyError(f"Missing required columns: {', '.join(sorted(missing))}")

    if df.empty:
        raise ValueError("Input DataFrame is empty.")

    df_plot = redistribute_calm_to_first_speed_class(df)
    calm_total = get_total_calm_frequency(df)

    calm_note = (
        f"Calm total: {calm_total:.2f}%\n"
        "Redistributed to 1.7 m/s class"
        if calm_total > 0.0
        else "Calm total: 0.00%"
    )

    theta = np.deg2rad(DIRECTION_ANGLES_DEG)
    width = np.deg2rad(45.0)

    fig, ax = plt.subplots(figsize=figsize, subplot_kw={"projection": "polar"})
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)

    cumulative = np.zeros(len(DIRECTION_ANGLES_DEG), dtype=float)
    colors = plt.cm.viridis(np.linspace(0.15, 0.85, len(REPRESENTATIVE_SPEED_CLASSES)))

    for color, representative_speed, label in zip(
        colors,
        REPRESENTATIVE_SPEED_CLASSES,
        REPRESENTATIVE_SPEED_LABELS,
    ):
        speed_mask = np.isclose(df_plot["speed"].to_numpy(dtype=float), representative_speed, atol=1e-9)
        speed_df = df_plot.loc[speed_mask]

        values = []
        for angle_deg in DIRECTION_ANGLES_DEG:
            total = float(speed_df.loc[speed_df["direction_deg"] == angle_deg, "frequency"].sum())
            values.append(total)

        values = np.asarray(values, dtype=float)

        ax.bar(
            theta,
            values,
            width=width,
            bottom=cumulative,
            align="center",
            edgecolor="white",
            color=color,
            label=label,
        )
        cumulative += values

    ax.set_title("Wind Rose", fontsize=14, fontweight="bold", pad=20)
    ax.set_thetagrids(DIRECTION_ANGLES_DEG, labels=["N", "NE", "E", "SE", "S", "SW", "W", "NW"])
    ax.legend(
        title="Representative speed class",
        loc="upper left",
        bbox_to_anchor=(1.08, 1.0),
        borderaxespad=0.0,
    )

    fig.text(
        0.51, 0.58,
        calm_note,
        ha="left",
        va="top",
        fontsize=9,
        bbox=dict(boxstyle="round", facecolor="white", alpha=0.85, edgecolor="gray"),
    )

    fig.tight_layout(rect=[0, 0.02, 0.80, 1.0])
    return fig


def create_wind_rose_plot(df, figsize=(8, 8)):
    """
    Create a wind rose plot.

    Returns
    -------
    tuple
        (fig, status, message)
    """
    try:
        fig = create_matplotlib_polar_wind_rose(df, figsize=figsize)
        return (
            fig,
            "matplotlib_polar_symos",
            "Wind rose created using the 3 representative SYMOS speed classes (1.7, 5.0, 11.0 m/s).",
        )
    except Exception as exc:
        return None, "failed", f"Could not create wind rose plot: {exc}"


# -------------------------------------------------------------------
# 4. REPORT GENERATION
# -------------------------------------------------------------------
def generate_text_report(stats, rose_plot_status=None, rose_plot_message=""):
    """
    Generate a plain-text report from computed statistics.
    """
    report_lines = []

    report_lines.append("=" * 60)
    report_lines.append("WIND ROSE ANALYSIS REPORT")
    report_lines.append("=" * 60)
    report_lines.append("")

    report_lines.append(f"Total records: {stats['total_records']}")
    report_lines.append(f"Stability classes: {', '.join(stats['stability_classes'])}")
    report_lines.append(
        "Representative speed classes: "
        + ", ".join(f"{value:.1f} m/s" for value in stats["available_speed_classes"])
    )
    report_lines.append(
        f"Wind speed range: {stats['speed_range'][0]} - {stats['speed_range'][1]} m/s"
    )
    report_lines.append(f"Total calm frequency: {stats['total_calm_frequency']:.2f}%")
    report_lines.append("")

    report_lines.append(
        f"Overall dominant wind direction: "
        f"{stats['dominant_direction_name']} ({stats['dominant_value']:.2f}%)"
    )
    report_lines.append("")

    report_lines.append("Direction Frequencies (%):")
    report_lines.append("-" * 40)
    for direction_code, total in stats["direction_totals"].items():
        direction_name = DIRECTION_TO_NAME.get(direction_code, direction_code)
        report_lines.append(f"  {direction_name:<12} : {total:6.2f}%")

    report_lines.append("")
    report_lines.append(
        "Note: For calculation-consistent visualization, calm frequency is "
        "redistributed into the 1.7 m/s class according to directional weights "
        "of that class, as in the original plugin."
    )

    report_lines.append("")
    report_lines.append("Statistics by Stability Class:")
    report_lines.append("-" * 60)

    header = f"{'Class':<6} {'Total %':<10} {'Dominant Dir':<15} {'Value %':<10} {'Calm %':<8}"
    report_lines.append(header)
    report_lines.append("-" * len(header))

    for class_id, class_stat in stats["class_stats"].items():
        line = (
            f"{class_id:<6} "
            f"{class_stat['total_frequency']:<10.2f} "
            f"{class_stat['dominant_dir_name']:<15} "
            f"{class_stat['dominant_value']:<10.2f} "
            f"{class_stat['calm_frequency']:<8.2f}"
        )
        report_lines.append(line)

    report_lines.append("")

    if rose_plot_status:
        report_lines.append("Wind Rose Plot Status:")
        report_lines.append("-" * 40)
        report_lines.append(f"  Status  : {rose_plot_status}")
        if rose_plot_message:
            report_lines.append(f"  Message : {rose_plot_message}")
        report_lines.append("")

    report_lines.append("=" * 60)

    return "\n".join(report_lines)


# -------------------------------------------------------------------
# 5. MAIN ANALYSIS FUNCTION
# -------------------------------------------------------------------
def analyze_wind_rose(xml_path, create_plot=True):
    """
    Analyze wind-rose data and return all outputs in memory.
    """
    results = {
        "success": False,
        "error": None,
        "df": None,
        "stats": {},
        "bar_plot_bytes": None,
        "rose_plot_bytes": None,
        "rose_plot_status": None,
        "rose_plot_message": "",
        "report": "",
    }

    try:
        print(f"[ANALYZER] Loading XML: {xml_path}")

        df = parse_wind_rose_xml(xml_path)
        df = enrich_wind_rose_dataframe(df)

        results["df"] = df
        results["stats"] = calculate_statistics(df)
        results["success"] = True

        if create_plot:
            print("[ANALYZER] Creating plots...")

            fig_bar = create_simple_direction_plot(df)
            if fig_bar is not None:
                bar_buffer = BytesIO()
                fig_bar.savefig(bar_buffer, format="png", dpi=100, bbox_inches="tight")
                bar_buffer.seek(0)
                results["bar_plot_bytes"] = bar_buffer.getvalue()
                print(f"[ANALYZER] Bar plot created successfully ({len(results['bar_plot_bytes'])} bytes)")
                plt.close(fig_bar)
            else:
                print("[ANALYZER] Failed to create bar plot.")

            fig_rose, rose_status, rose_message = create_wind_rose_plot(df)
            results["rose_plot_status"] = rose_status
            results["rose_plot_message"] = rose_message

            if fig_rose is not None:
                rose_buffer = BytesIO()
                fig_rose.savefig(rose_buffer, format="png", dpi=100, bbox_inches="tight")
                rose_buffer.seek(0)
                results["rose_plot_bytes"] = rose_buffer.getvalue()
                print(
                    f"[ANALYZER] Wind rose created successfully "
                    f"using '{rose_status}' ({len(results['rose_plot_bytes'])} bytes)"
                )
                plt.close(fig_rose)
            else:
                print(f"[ANALYZER] Wind rose creation failed: {rose_message}")

        results["report"] = generate_text_report(
            results["stats"],
            rose_plot_status=results["rose_plot_status"],
            rose_plot_message=results["rose_plot_message"],
        )

    except Exception as exc:
        results["error"] = str(exc)
        results["success"] = False
        results["report"] = f"Analysis failed: {exc}"
        print(f"[ANALYZER] ERROR: {exc}")

    return results


# -------------------------------------------------------------------
# 6. EXPORT FUNCTIONS
# -------------------------------------------------------------------
def export_to_csv(df, output_path):
    """
    Export the DataFrame to a CSV file.
    """
    df.to_csv(output_path, index=False, encoding="utf-8")
    return os.path.abspath(output_path)


def export_bar_plot_to_file(plot_bytes, output_path):
    """
    Export bar-plot bytes to a PNG file.
    """
    if plot_bytes is None:
        raise ValueError("No bar plot data available to export.")

    with open(output_path, "wb") as file:
        file.write(plot_bytes)

    return os.path.abspath(output_path)


def export_wind_rose_to_file(plot_bytes, output_path):
    """
    Export wind-rose plot bytes to a PNG file.
    """
    if plot_bytes is None:
        raise ValueError("No wind rose plot data available to export.")

    with open(output_path, "wb") as file:
        file.write(plot_bytes)

    return os.path.abspath(output_path)
