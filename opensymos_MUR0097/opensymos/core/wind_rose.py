import numpy as np


class WindRose:
    def __init__(self, df):
        self.df = df
        self.detailed_wind_rose = []
        self.frequencies = None
        self._build_frequency_matrix()

    def _get_calm_by_stability(self):
        """
        Return calm-frequency value for each stability class.

        XML parser stores 'calm' repeatedly in each row of the same stability
        class, so it is enough to take the first value per class.
        """
        calm_by_stability = {}

        if "calm" not in self.df.columns:
            return calm_by_stability

        grouped = self.df.groupby(self.df["stability"].astype(str))
        for stability_class, group in grouped:
            if not group.empty:
                calm_by_stability[str(stability_class)] = float(group["calm"].iloc[0])

        return calm_by_stability

    def _redistribute_calm_to_first_speed_class(self, coarse_rows, combinations):
        """
        Replicate original plugin behaviour:
        calm frequency is redistributed into the first speed class (1.7 m/s)
        according to directional weights of that class.
        """
        calm_by_stability = self._get_calm_by_stability()

        # Find row index of the first speed class (1.7 m/s) for each stability class
        first_speed_row_index = {}
        for idx, (stability_class, representative_speed) in enumerate(combinations):
            if float(representative_speed) == 1.7 and stability_class not in first_speed_row_index:
                first_speed_row_index[stability_class] = idx

        for stability_class, row_index in first_speed_row_index.items():
            calm_value = calm_by_stability.get(stability_class, 0.0)
            if calm_value == 0.0:
                continue

            row = coarse_rows[row_index]
            row_sum = sum(row)

            if row_sum > 0.0:
                redistributed_row = []
                for value in row:
                    weight = value / row_sum
                    redistributed_row.append(value + weight * calm_value)
                coarse_rows[row_index] = redistributed_row
            else:
                # Robust fallback: if the first speed class has no directional
                # frequencies at all, distribute calm evenly.
                coarse_rows[row_index] = [calm_value / 8.0] * 8

        return coarse_rows

    def _build_frequency_matrix(self):
        # Ordered combinations exactly as they appear in the SYMOS XML/parser.
        combinations = [
            ("1", 1.7),
            ("2", 1.7),
            ("2", 5.0),
            ("3", 1.7),
            ("3", 5.0),
            ("3", 11.0),
            ("4", 1.7),
            ("4", 5.0),
            ("4", 11.0),
            ("5", 1.7),
            ("5", 5.0),
        ]

        direction_order = ["s", "sv", "v", "jv", "j", "jz", "z", "sz"]

        # Coarse 8-direction rows from the XML input.
        coarse_rows = []

        for stability_class, representative_speed in combinations:
            subset = self.df[
                (self.df["stability"].astype(str) == stability_class)
                & (self.df["speed"].astype(float) == float(representative_speed))
            ]

            row = []
            for direction_code in direction_order:
                match = subset[subset["direction"] == direction_code]
                if match.empty:
                    row.append(0.0)
                else:
                    row.append(float(match["frequency"].iloc[0]))

            coarse_rows.append(row)

        # IMPORTANT:
        # replicate original plugin behaviour by redistributing calm
        # into the first speed class (1.7 m/s) for each stability class
        coarse_rows = self._redistribute_calm_to_first_speed_class(coarse_rows, combinations)

        azimuth_breaks = [0, 45, 90, 135, 180, 225, 270, 315]
        self.detailed_wind_rose = []

        # Interpolate directional distribution from 8 sectors to 360 azimuths.
        for row_index in range(11):
            row_360 = []

            for azimuth in range(360):
                if azimuth < 315:
                    for sector_index in range(0, 7):
                        if azimuth_breaks[sector_index] <= azimuth < azimuth_breaks[sector_index + 1]:
                            base_azimuth = azimuth_breaks[sector_index]
                            base_frequency = coarse_rows[row_index][sector_index]
                            next_frequency = coarse_rows[row_index][sector_index + 1]
                            break
                else:
                    base_azimuth = 315
                    base_frequency = coarse_rows[row_index][7]
                    next_frequency = coarse_rows[row_index][0]

                interpolated_frequency = (
                    (1.0 / 4500.0)
                    * (
                        base_frequency
                        + ((azimuth - base_azimuth) / 45.0)
                        * (next_frequency - base_frequency)
                    )
                )
                row_360.append(interpolated_frequency)

            self.detailed_wind_rose.append(row_360)

        self.frequencies = np.array(self.detailed_wind_rose, dtype=float)

    def get_frequencies(self):
        return self.frequencies

    def get_frequency(self, stability_class, wind_speed, direction):
        row_index = self._get_row_index(stability_class, wind_speed)
        if row_index is None:
            return 0.0
        return self.frequencies[row_index, int(direction) % 360]

    def _get_row_index(self, stability_class, speed_value):
        speed_value = float(speed_value)
        stability_class = int(stability_class)

        if speed_value < 2.5:
            mapping = {1: 0, 2: 1, 3: 3, 4: 6, 5: 9}
        elif speed_value < 7.5:
            mapping = {2: 2, 3: 4, 4: 7, 5: 10}
        else:
            mapping = {3: 5, 4: 8}

        return mapping.get(stability_class, None)

    def debug_print_totals(self):
        labels = [
            "1 slow",
            "2 slow",
            "2 moderate",
            "3 slow",
            "3 moderate",
            "3 strong",
            "4 slow",
            "4 moderate",
            "4 strong",
            "5 slow",
            "5 moderate",
        ]
        for row_index, label in enumerate(labels):
            print(f"{row_index}: {label} -> {self.frequencies[row_index, :].sum()}")
        print("TOTAL =", self.frequencies.sum())

        if "calm" in self.df.columns:
            calm_total = float(
                self.df.groupby(self.df["stability"].astype(str))["calm"].first().sum()
            )
            print("CALM TOTAL =", calm_total)