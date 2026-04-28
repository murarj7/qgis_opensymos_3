"""
Worker class for running SYMOS calculations in background thread.
"""
from qgis.PyQt.QtCore import QObject, pyqtSignal


class CalculationWorker(QObject):
    """Worker for background calculation."""

    progress = pyqtSignal(int)
    log = pyqtSignal(str)
    finished = pyqtSignal(object)

    def __init__(
        self,
        sources,
        receptors,
        dem,
        wind_rose,
        calculation_type,
        pollutant,
        receptor_height,
        limit_value=None,
    ):
        super().__init__()
        self.sources = sources
        self.receptors = receptors
        self.dem = dem
        self.wind_rose = wind_rose
        self.calculation_type = calculation_type
        self.pollutant = pollutant
        self.receptor_height = receptor_height
        self.limit_value = limit_value
        self.aborted = False
        self._last_percent = -1

    def abort(self):
        """Request abortion of calculation."""
        self.aborted = True
        self.log.emit("Abort requested by user...")

    def _should_abort(self):
        """Return True if calculation should stop."""
        return self.aborted

    def run(self):
        """Run the actual SYMOS calculation."""
        try:
            if self.aborted:
                self.log.emit("Calculation aborted before start.")
                self.finished.emit(None)
                return

            self.log.emit("Warming up calculation engine...")

            import numpy as np
            import math

            test_array = np.zeros((10, 10))
            for i in range(10):
                if self.aborted:
                    self.log.emit("Calculation aborted during warm-up.")
                    self.finished.emit(None)
                    return
                for j in range(10):
                    test_array[i, j] = math.sin(i) * math.cos(j)
            del test_array

            if self.aborted:
                self.log.emit("Calculation aborted before calculator startup.")
                self.finished.emit(None)
                return

            self.log.emit("Warm-up complete. Starting SYMOS calculation...")

            from .calculator import Calculator

            calculator = Calculator(
                sources=self.sources,
                receptors=self.receptors,
                dem=self.dem,
                wind_rose=self.wind_rose,
            )

            def progress_callback(current, total):
                if total <= 0:
                    percent = 0
                else:
                    percent = int((current / total) * 100)
                    percent = max(0, min(100, percent))

                if percent != self._last_percent:
                    self._last_percent = percent
                    self.progress.emit(percent)

            calculator.set_progress_callback(progress_callback)
            calculator.set_log_callback(self.log.emit)
            calculator.set_abort_callback(lambda: self.aborted)

            self.log.emit(f"Calculation type: {self.calculation_type}")
            self.log.emit(f"Pollutant: {self.pollutant}")
            self.log.emit(f"Receptor height: {self.receptor_height} m")
            if self.limit_value is not None:
                self.log.emit(f"Limit value: {self.limit_value} μg/m³")

            results = calculator.calculate(
                calculation_type=self.calculation_type,
                pollutant=self.pollutant,
                receptor_height=self.receptor_height,
                limit_value=self.limit_value,
            )

            if self.aborted:
                self.log.emit("Calculation aborted.")
                self.finished.emit(None)
                return

            if results and not results.is_empty():
                self.progress.emit(100)
                self.log.emit(f"Calculation completed. Generated {results.count()} results.")
                self.finished.emit(results)
            else:
                if self.aborted:
                    self.log.emit("Calculation aborted.")
                else:
                    self.log.emit("Calculation failed - no results generated.")
                self.finished.emit(None)

        except Exception as e:
            self.log.emit(f"ERROR: {str(e)}")
            import traceback
            traceback.print_exc()
            self.finished.emit(None)