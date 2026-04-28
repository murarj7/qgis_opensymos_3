import xml.etree.ElementTree as ET

import pandas as pd


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


def parse_wind_rose_xml(xml_path):
    """
    Parse a SYMOS wind-rose XML file.

    The XML keeps Czech element names such as <trida_stability>, <rychlost>,
    <cetnosti> and <bezvetri>. Python-side names are normalized to English.

    Returns
    -------
    pandas.DataFrame
        Columns:
        - stability: stability class id (1-5)
        - speed: representative wind-speed class value (m/s)
        - direction: direction code (s, sv, v, jv, j, jz, z, sz)
        - frequency: frequency in percent
        - calm: calm-condition frequency in percent
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()

    rows = []

    for stability_elem in root.findall("trida_stability"):
        stability_id = stability_elem.get("id")
        calm_elem = stability_elem.find("bezvetri")
        if calm_elem is None:
            raise ValueError(f"Missing 'bezvetri' element for stability class {stability_id}.")

        calm_value = calm_elem.get("value")
        if calm_value is None:
            raise ValueError(f"Missing calm value for stability class {stability_id}.")

        calm_frequency = float(calm_value)

        for speed_elem in stability_elem.findall("rychlost"):
            speed_value = speed_elem.get("value")
            if speed_value is None:
                raise ValueError(f"Missing speed value for stability class {stability_id}.")

            direction_frequencies = speed_elem.find("cetnosti")
            if direction_frequencies is None:
                raise ValueError(
                    f"Missing 'cetnosti' element for stability class {stability_id}, speed {speed_value}."
                )

            for direction_code in DIRECTION_CODES:
                frequency_value = direction_frequencies.get(direction_code)
                if frequency_value is None:
                    raise ValueError(
                        f"Missing frequency for direction '{direction_code}', "
                        f"stability class {stability_id}, speed {speed_value}."
                    )

                rows.append(
                    {
                        "stability": str(stability_id),
                        "speed": float(speed_value),
                        "direction": direction_code,
                        "frequency": float(frequency_value),
                        "calm": calm_frequency,
                    }
                )

    return pd.DataFrame(rows)


def get_direction_degrees(direction_code):
    """
    Convert a direction code to degrees.
    """
    return DIRECTION_TO_DEGREES.get(direction_code, 0)


def add_degrees_column(df):
    """
    Add a direction_deg column to a DataFrame.
    """
    result = df.copy()
    result["direction_deg"] = result["direction"].apply(get_direction_degrees)
    return result
