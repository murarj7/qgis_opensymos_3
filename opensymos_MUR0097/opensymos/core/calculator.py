import time
import math
from qgis.core import QgsMessageLog, Qgis

from .source import Source
from .receptor import Receptor
from .result import Result
from .results_collection import ResultsCollection
from .terrain import Terrain
from . import calculations as calc


class Calculator:
    """
    Main calculator class that orchestrates the entire dispersion calculation.
    """

    MAX_SHORT_TERM = 1
    ANNUAL_AVERAGE = 2
    EXCEEDANCE_TIME = 3

    def __init__(self, sources, receptors, dem=None, wind_rose=None):
        self.sources = sources
        self.receptors = receptors
        self.dem = dem
        self.wind_rose = wind_rose

        self.source_receptor_data = None
        self.crs = None
        self.results = ResultsCollection()

        self.total_steps = 0
        self.current_step = 0
        self.progress_callback = None
        self.log_callback = None
        self.abort_callback = None

    def _get_vzor_wind_row_index(self, stability_class, wind_speed):
        if wind_speed < 2.5:
            mapping = {1: 0, 2: 1, 3: 3, 4: 6, 5: 9}
        elif wind_speed < 7.5:
            mapping = {2: 2, 3: 4, 4: 7, 5: 10}
        else:
            mapping = {3: 5, 4: 8}
        return mapping.get(stability_class, None)

    def set_progress_callback(self, callback):
        self.progress_callback = callback

    def set_log_callback(self, callback):
        self.log_callback = callback

    def set_abort_callback(self, callback):
        self.abort_callback = callback

    def _should_abort(self):
        return callable(self.abort_callback) and self.abort_callback()

    def _log(self, message):
        if self.log_callback:
            self.log_callback(message)
        else:
            print(message)

    def _update_progress(self, current=None, total=None):
        if self.progress_callback:
            if current is None:
                current = self.current_step
            if total is None:
                total = self.total_steps
            self.progress_callback(current, total)

    def _update_progress_percent(self, percent):
        """Update progress directly in percent."""
        percent = max(0, min(100, int(percent)))
        if self.progress_callback:
            self.progress_callback(percent, 100)

    def _validate_inputs(self, calculation_type):
        if not self.sources:
            return False, "No sources provided"

        if not self.receptors:
            return False, "No receptors provided"

        for i, source in enumerate(self.sources):
            if self._should_abort():
                return False, "Calculation aborted"
            valid, warnings, fallbacks = source.validate_with_fallback()
            if not valid:
                error_msg = warnings[0] if warnings else "Unknown error"
                return False, f"Source {i} invalid: {error_msg}"
            if warnings:
                for warning in warnings:
                    self._log(f"Warning for source {i}: {warning}")

        for i, receptor in enumerate(self.receptors):
            if self._should_abort():
                return False, "Calculation aborted"
            valid, msg = receptor.validate()
            if not valid:
                return False, f"Receptor {i} invalid: {msg}"

        if calculation_type in [self.ANNUAL_AVERAGE, self.EXCEEDANCE_TIME]:
            if self.wind_rose is None:
                self._log("⚠ Warning: No wind rose data - using simplified calculation (for testing)")

        return True, "OK"

    def precompute_data(self):
        """
        Precompute all data that does not change during calculation:
        - distances between each source and receptor
        - azimuths
        - maximum terrain heights
        - terrain profiles
        """
        self._log("Precomputing source-receptor data ...")

        n_sources = len(self.sources)
        n_receptors = len(self.receptors)

        self.source_receptor_data = []

        precompute_total = max(1, n_sources * n_receptors)
        precompute_step = 0

        for i, source in enumerate(self.sources):
            if self._should_abort():
                self._log("Calculation aborted during precomputation.")
                return None

            self._log(f"  Processing source {i + 1}/{n_sources}")
            source_data = []

            for j, receptor in enumerate(self.receptors):
                if self._should_abort():
                    self._log("Calculation aborted during precomputation.")
                    return None

                dx = source.x - receptor.x
                dy = source.y - receptor.y
                distance = math.sqrt(dx * dx + dy * dy)

                azimuth = calc.calculate_azimuth(
                    source.x,
                    source.y,
                    receptor.x,
                    receptor.y,
                )

                pair_data = {
                    "distance": distance,
                    "azimuth": azimuth,
                    "profile": None,
                    "max_height": None,
                    "pixel_size": None,
                }

                if self.dem is not None:
                    profile, max_height = self.dem.get_profile_and_max_height(
                        source.x,
                        source.y,
                        receptor.x,
                        receptor.y,
                    )

                    if profile is not None and max_height is not None:
                        pair_data["profile"] = profile
                        pair_data["max_height"] = max_height
                        pair_data["pixel_size"] = self.dem.pixel_size
                    else:
                        pair_data["max_height"] = max(source.z, receptor.z)
                        self._log(
                            f"    Warning: terrain profile missing (source {i}, receptor {j})"
                        )
                else:
                    pair_data["max_height"] = max(source.z, receptor.z)

                source_data.append(pair_data)

                precompute_step += 1
                if precompute_step % 50 == 0 or precompute_step == precompute_total:
                    phase_percent = (precompute_step / precompute_total) * 10.0
                    self._update_progress_percent(phase_percent)

                if (j + 1) % 100 == 0:
                    self._log(f"    Receptor {j + 1}/{n_receptors}")

            self.source_receptor_data.append(source_data)

        self._log(f"Precomputed data for {n_sources} sources × {n_receptors} receptors")

        n_classes = 5
        n_directions = 360
        self.total_steps = n_receptors * n_classes * n_directions * max(1, n_sources)
        self._log(f"Total calculation steps: {self.total_steps}")

        return True

    def calculate_max_short_term(self, pollutant, receptor_height):
        self._log("\n=== MAXIMUM SHORT-TERM CONCENTRATION CALCULATION ===")
        self._log(f"Pollutant: {pollutant}")
        self._log(f"Receptor height: {receptor_height} m")
        self._log(f"Sources: {len(self.sources)}")
        self._log(f"Receptors: {len(self.receptors)}")

        valid, msg = self._validate_inputs(self.MAX_SHORT_TERM)
        if not valid:
            self._log(f"Validation failed: {msg}")
            return None

        if self.source_receptor_data is None:
            if self.precompute_data() is None:
                return None

        start_time = time.time()
        results = ResultsCollection()

        for r in self.receptors:
            r.set_height_above(receptor_height)

        self.current_step = 0
        total_receptors = len(self.receptors)
        is_particle = pollutant == "dust"

        wind_speed_lists = {
            1: [1.5, 1.6, 1.7, 1.8, 1.9, 2.0],
            2: [1.5, 1.6, 1.7, 1.8, 1.9, 2.0, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 3.0, 3.2, 3.4, 3.6, 3.8, 4.0, 4.2, 4.4, 4.6, 4.8, 5.0],
            3: [1.5, 1.6, 1.7, 1.8, 1.9, 2.0, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 3.0, 3.2, 3.4, 3.6, 3.8, 4.0, 4.2, 4.4, 4.6, 4.8, 5.0, 5.2, 5.4, 5.6, 5.8, 6.0, 6.2, 6.4, 6.6, 6.8, 7.0, 7.5, 8.0, 8.5, 9.0, 9.5, 10.0, 10.5, 11.0, 11.5, 12.0, 12.5, 13.0, 13.5, 14.0, 14.5, 15.0],
            4: [1.5, 1.6, 1.7, 1.8, 1.9, 2.0, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 3.0, 3.2, 3.4, 3.6, 3.8, 4.0, 4.2, 4.4, 4.6, 4.8, 5.0, 5.2, 5.4, 5.6, 5.8, 6.0, 6.2, 6.4, 6.6, 6.8, 7.0, 7.5, 8.0, 8.5, 9.0, 9.5, 10.0, 10.5, 11.0, 11.5, 12.0, 12.5, 13.0, 13.5, 14.0, 14.5, 15.0],
            5: [1.5, 1.6, 1.7, 1.8, 1.9, 2.0, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 3.0, 3.2, 3.4, 3.6, 3.8, 4.0, 4.2, 4.4, 4.6, 4.8, 5.0],
        }

        total_wind_speed_steps = sum(len(speed_list) for speed_list in wind_speed_lists.values())
        total_steps = total_receptors * total_wind_speed_steps * 360 * max(1, len(self.sources))
        self.total_steps = total_steps
        self.current_step = 0

        for r_idx, receptor in enumerate(self.receptors):
            if self._should_abort():
                self._log("Calculation aborted.")
                return None

            if (r_idx + 1) % 10 == 0:
                self._log(f"Processing receptor {r_idx + 1}/{total_receptors}")

            selected_11 = []

            overall_max = -1.0
            overall_max_stability = None
            overall_max_wind_speed = None
            overall_max_direction = None

            for class_const in calc.CLASS_CONSTANTS:
                if self._should_abort():
                    self._log("Calculation aborted.")
                    return None

                stability_class = class_const["class"]
                wind_speeds = wind_speed_lists[stability_class]

                for wind_speed in wind_speeds:
                    if self._should_abort():
                        self._log("Calculation aborted.")
                        return None

                    max_for_speed = 0.0

                    for direction in range(360):
                        if self._should_abort():
                            self._log("Calculation aborted.")
                            return None

                        conc = 0.0

                        for s_idx, source in enumerate(self.sources):
                            if self._should_abort():
                                self._log("Calculation aborted.")
                                return None

                            pair_data = self.source_receptor_data[s_idx][r_idx]

                            c = calc.calculate_concentration_point(
                                source,
                                receptor,
                                stability_class,
                                wind_speed,
                                direction,
                                pair_data["distance"],
                                pair_data["azimuth"],
                                pair_data["max_height"],
                                pair_data["profile"],
                                pair_data["pixel_size"],
                                pollutant,
                                is_particle,
                            )
                            conc += c

                            self.current_step += 1
                            if self.current_step % 2000 == 0 or self.current_step == self.total_steps:
                                phase_percent = 10.0 + (self.current_step / self.total_steps) * 90.0
                                self._update_progress_percent(phase_percent)

                        if conc > max_for_speed:
                            max_for_speed = conc

                        if conc > overall_max:
                            overall_max = conc
                            overall_max_stability = stability_class
                            overall_max_wind_speed = wind_speed
                            overall_max_direction = direction

                    if stability_class == 1 and wind_speed == 1.7:
                        selected_11.append(max_for_speed)
                    elif stability_class == 2 and wind_speed in (1.7, 5.0):
                        selected_11.append(max_for_speed)
                    elif stability_class == 3 and wind_speed in (1.7, 5.0, 11.0):
                        selected_11.append(max_for_speed)
                    elif stability_class == 4 and wind_speed in (1.7, 5.0, 11.0):
                        selected_11.append(max_for_speed)
                    elif stability_class == 5 and wind_speed in (1.7, 5.0):
                        selected_11.append(max_for_speed)

            if len(selected_11) != 11:
                raise ValueError(f"Expected 11 selected concentration values, got {len(selected_11)}")

            result = Result(receptor.id, receptor.x, receptor.y)
            result.set_max_short_term(
                selected_11,
                overall_max,
                max_stability=overall_max_stability,
                max_wind_speed=overall_max_wind_speed,
                max_direction=overall_max_direction,
            )
            results.add_result(result)

            phase_percent = 10.0 + ((r_idx + 1) / total_receptors) * 90.0
            self._update_progress_percent(phase_percent)

        elapsed = time.time() - start_time
        self._log(f"\nCalculation completed in {elapsed:.1f} seconds")
        self._log(f"Generated {len(results.results)} results")

        results.set_metadata(None, pollutant, self.MAX_SHORT_TERM)
        return results

    def calculate_annual_average(self, pollutant, receptor_height):
        self._log("\n=== ANNUAL AVERAGE CONCENTRATION CALCULATION ===")
        self._log(f"Pollutant: {pollutant}")
        self._log(f"Receptor height: {receptor_height} m")

        valid, msg = self._validate_inputs(self.ANNUAL_AVERAGE)
        if not valid:
            self._log(f"Validation failed: {msg}")
            return None

        if self.source_receptor_data is None:
            if self.precompute_data() is None:
                return None

        if self.wind_rose is not None:
            wind_freq = self.wind_rose.get_frequencies()
        else:
            self._log("⚠ No wind rose data - using uniform distribution")
            import numpy as np
            wind_freq = np.ones((11, 360)) / (11 * 360)

        start_time = time.time()
        results = ResultsCollection()

        for r in self.receptors:
            r.set_height_above(receptor_height)

        is_particle = pollutant == "dust"
        total_receptors = len(self.receptors)

        self.total_steps = max(1, total_receptors)
        self.current_step = 0

        for r_idx, receptor in enumerate(self.receptors):
            if self._should_abort():
                self._log("Calculation aborted.")
                return None

            if (r_idx + 1) % 10 == 0:
                self._log(f"\nProcessing receptor {r_idx + 1}/{total_receptors}")

            annual_sum = 0.0

            for class_const in calc.CLASS_CONSTANTS:
                if self._should_abort():
                    self._log("Calculation aborted.")
                    return None

                stability_class = class_const["class"]
                wind_speeds = calc.get_wind_speed_classes_for_stability(stability_class, "annual")

                for wind_speed in wind_speeds:
                    if self._should_abort():
                        self._log("Calculation aborted.")
                        return None

                    row_idx = self._get_vzor_wind_row_index(stability_class, wind_speed)

                    for direction in range(360):
                        if self._should_abort():
                            self._log("Calculation aborted.")
                            return None

                        freq = wind_freq[row_idx][direction] if row_idx is not None else 0.0
                        if freq <= 0:
                            continue

                        conc = 0.0

                        for s_idx, source in enumerate(self.sources):
                            if self._should_abort():
                                self._log("Calculation aborted.")
                                return None

                            pair_data = self.source_receptor_data[s_idx][r_idx]

                            c = calc.calculate_concentration_point(
                                source,
                                receptor,
                                stability_class,
                                wind_speed,
                                direction,
                                pair_data["distance"],
                                pair_data["azimuth"],
                                pair_data["max_height"],
                                pair_data["profile"],
                                pair_data["pixel_size"],
                                pollutant,
                                is_particle,
                                calculation_type="annual",
                            )

                            contrib = c * source.annual_utilization
                            conc += contrib

                        annual_sum += conc * freq

            result = Result(receptor.id, receptor.x, receptor.y)
            result.set_annual_average(annual_sum)
            results.add_result(result)

            self.current_step = r_idx + 1
            phase_percent = 10.0 + (self.current_step / total_receptors) * 90.0
            self._update_progress_percent(phase_percent)

        elapsed = time.time() - start_time
        self._log(f"\nCalculation completed in {elapsed:.1f} seconds")

        results.set_metadata(None, pollutant, self.ANNUAL_AVERAGE)
        return results

    def calculate_exceedance_time(self, pollutant, receptor_height, limit_value):
        self._log("\n=== EXCEEDANCE TIME CALCULATION ===")
        self._log(f"Pollutant: {pollutant}")
        self._log(f"Receptor height: {receptor_height} m")
        self._log(f"Limit value: {limit_value} μg/m³")

        valid, msg = self._validate_inputs(self.EXCEEDANCE_TIME)
        if not valid:
            self._log(f"Validation failed: {msg}")
            return None

        if self.source_receptor_data is None:
            if self.precompute_data() is None:
                return None

        if self.wind_rose is not None:
            wind_freq = self.wind_rose.get_frequencies()
        else:
            self._log("⚠ No wind rose data - using uniform distribution")
            import numpy as np
            wind_freq = np.ones((11, 360)) / (11 * 360)

        start_time = time.time()
        results = ResultsCollection()

        for r in self.receptors:
            r.set_height_above(receptor_height)

        total_receptors = len(self.receptors)
        is_particle = pollutant == "dust"
        self.total_steps = max(1, total_receptors)
        self.current_step = 0

        sorted_sources_with_idx = sorted(
            list(enumerate(self.sources)),
            key=lambda item: item[1].annual_utilization,
            reverse=True,
        )

        for r_idx, receptor in enumerate(self.receptors):
            if self._should_abort():
                self._log("Calculation aborted.")
                return None

            if (r_idx + 1) % 10 == 0:
                self._log(f"\nProcessing receptor {r_idx + 1}/{total_receptors}")

            exceedance_sum = 0.0

            for class_const in calc.CLASS_CONSTANTS:
                if self._should_abort():
                    self._log("Calculation aborted.")
                    return None

                stability_class = class_const["class"]
                wind_speeds = calc.get_wind_speed_classes_for_stability(stability_class, "annual")

                for wind_speed in wind_speeds:
                    if self._should_abort():
                        self._log("Calculation aborted.")
                        return None

                    row_idx = self._get_vzor_wind_row_index(stability_class, wind_speed)

                    for direction in range(360):
                        if self._should_abort():
                            self._log("Calculation aborted.")
                            return None

                        if self.wind_rose is not None:
                            freq = wind_freq[row_idx][direction] if row_idx is not None else 0.0
                        else:
                            freq = 1.0 / (11 * 360)

                        if freq <= 0:
                            continue

                        cumulative_conc = 0.0
                        t_r_phi_j = 0.0

                        for s_idx, source in sorted_sources_with_idx:
                            if self._should_abort():
                                self._log("Calculation aborted.")
                                return None

                            pair_data = self.source_receptor_data[s_idx][r_idx]

                            c = calc.calculate_concentration_point(
                                source,
                                receptor,
                                stability_class,
                                wind_speed,
                                direction,
                                pair_data["distance"],
                                pair_data["azimuth"],
                                pair_data["max_height"],
                                pair_data["profile"],
                                pair_data["pixel_size"],
                                pollutant,
                                is_particle,
                                calculation_type="exceedance",
                            )

                            cumulative_conc += c

                            if cumulative_conc > limit_value:
                                t_r_phi_j = source.annual_utilization
                                break

                        exceedance_sum += t_r_phi_j * freq

            exceedance_hours = exceedance_sum * 8760.0

            result = Result(receptor.id, receptor.x, receptor.y)
            result.set_exceedance_time(exceedance_hours)
            results.add_result(result)

            self.current_step = r_idx + 1
            phase_percent = 10.0 + (self.current_step / total_receptors) * 90.0
            self._update_progress_percent(phase_percent)

        elapsed = time.time() - start_time
        self._log(f"\nCalculation completed in {elapsed:.1f} seconds")

        results.set_metadata(None, pollutant, self.EXCEEDANCE_TIME)
        return results

    def calculate(self, calculation_type, pollutant, receptor_height, limit_value=None):
        try:
            if self._should_abort():
                self._log("Calculation aborted before start.")
                return None

            if calculation_type == self.MAX_SHORT_TERM:
                return self.calculate_max_short_term(pollutant, receptor_height)
            elif calculation_type == self.ANNUAL_AVERAGE:
                return self.calculate_annual_average(pollutant, receptor_height)
            elif calculation_type == self.EXCEEDANCE_TIME:
                if limit_value is None:
                    self._log("Error: limit_value required for exceedance time calculation")
                    return None
                return self.calculate_exceedance_time(pollutant, receptor_height, limit_value)
            else:
                self._log(f"Error: Unknown calculation type {calculation_type}")
                return None

        except Exception as e:
            self._log(f"Error during calculation: {str(e)}")
            import traceback
            traceback.print_exc()
            return None