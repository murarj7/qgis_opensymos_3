"""
Core calculation modules for SYMOS dispersion model.
"""
from .source import Source
from .receptor import Receptor
from .result import Result
from .results_collection import ResultsCollection
from .calculator import Calculator
from .calculation_worker import CalculationWorker
from .wind_rose import WindRose
from .terrain import Terrain

# Optional: expose key functions from calculations
from .calculations import (
    calculate_azimuth,
    calculate_wind_speed_at_height,
    calculate_concentration_point,
    CLASS_CONSTANTS,
    REMOVAL_COEFFICIENTS
)

__all__ = [
    'Source',
    'Receptor', 
    'Result',
    'ResultsCollection',
    'Calculator',
    'calculate_azimuth',
    'calculate_wind_speed_at_height',
    'calculate_concentration_point',
    'CLASS_CONSTANTS',
    'REMOVAL_COEFFICIENTS'
]