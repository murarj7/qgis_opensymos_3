"""
Module for calculation result representation in SYMOS dispersion model.
Each receptor point gets a Result object with calculated concentrations.
"""
from qgis.core import (QgsVectorLayer, QgsField, QgsFeature, QgsGeometry,
                       QgsPointXY, QgsProject, QgsWkbTypes)
from qgis.PyQt.QtCore import QVariant

class Result:
    """
    Represents calculation results for a single receptor point.
    
    Supports three types of results:
    - Maximum short-term concentrations (11 values + total max)
    - Annual average concentration
    - Time of limit exceedance (hours/year)
    """
    
    # Class constants for result types
    TYPE_MAX_SHORT_TERM = 1
    TYPE_ANNUAL_AVERAGE = 2
    TYPE_EXCEEDANCE_TIME = 3
    
    # Names for the 11 concentration values (for reference)
    CONCENTRATION_NAMES = [
        'c_cls1_v1',   # Class 1, speed 1.7 m/s
        'c_cls2_v1',   # Class 2, speed 1.7 m/s
        'c_cls2_v2',   # Class 2, speed 5.0 m/s
        'c_cls3_v1',   # Class 3, speed 1.7 m/s
        'c_cls3_v2',   # Class 3, speed 5.0 m/s
        'c_cls3_v3',   # Class 3, speed 11.0 m/s
        'c_cls4_v1',   # Class 4, speed 1.7 m/s
        'c_cls4_v2',   # Class 4, speed 5.0 m/s
        'c_cls4_v3',   # Class 4, speed 11.0 m/s
        'c_cls5_v1',   # Class 5, speed 1.7 m/s
        'c_cls5_v2'    # Class 5, speed 5.0 m/s
    ]
    
    def __init__(self, receptor_id, x, y):
        """
        Initialize a result container for a receptor point.
        
        Args:
            receptor_id: int/str - identifier matching source receptor
            x: float - x coordinate
            y: float - y coordinate
        """
        self.id = receptor_id
        self.x = x
        self.y = y
        
        # Result type (will be set by specific methods)
        self.result_type = None
        
        # Maximum short-term concentrations
        self.max_values = None          # List of 11 values
        self.max_total = None           # Overall maximum
        self.max_stability = None       # Stability class for c_max
        self.max_wind_speed = None      # Wind speed for c_max
        self.max_direction = None       # Wind direction for c_max
        
        # Annual average
        self.annual_average = None      # μg/m³
        
        # Exceedance time
        self.exceedance_time = None     # hours/year
    
    def set_max_short_term(
        self,
        values,
        total_max,
        max_stability=None,
        max_wind_speed=None,
        max_direction=None,
    ):
        """
        Set maximum short-term concentrations.

        Args:
            values: list - 11 concentration values in standard order
            total_max: float - overall maximum concentration
            max_stability: int or None - stability class for c_max
            max_wind_speed: float or None - wind speed for c_max
            max_direction: int or None - wind direction for c_max

        Returns:
            bool: True if successful
        """
        if len(values) != 11:
            raise ValueError(f"Expected 11 concentration values, got {len(values)}")

        self.result_type = self.TYPE_MAX_SHORT_TERM
        self.max_values = values
        self.max_total = total_max
        self.max_stability = max_stability
        self.max_wind_speed = max_wind_speed
        self.max_direction = max_direction
        return True
    
    def set_annual_average(self, value):
        """
        Set annual average concentration.
        
        Args:
            value: float - annual average concentration [μg/m³]
        """
        self.result_type = self.TYPE_ANNUAL_AVERAGE
        self.annual_average = value
    
    def set_exceedance_time(self, hours):
        """
        Set time of limit exceedance.
        
        Args:
            hours: float - exceedance time [hours/year]
        """
        self.result_type = self.TYPE_EXCEEDANCE_TIME
        self.exceedance_time = hours
    
    def get_value_by_type(self, result_type):
        """
        Get result value(s) by type.
        
        Args:
            result_type: int - one of TYPE_ constants
        
        Returns:
            appropriate value (list for max short-term, float for others)
        """
        if result_type == self.TYPE_MAX_SHORT_TERM:
            return self.max_values, self.max_total
        elif result_type == self.TYPE_ANNUAL_AVERAGE:
            return self.annual_average
        elif result_type == self.TYPE_EXCEEDANCE_TIME:
            return self.exceedance_time
        else:
            raise ValueError(f"Unknown result type: {result_type}")
    
    def validate(self):
        """
        Check if result has valid data based on its type.
        
        Returns:
            tuple: (is_valid, error_message)
        """
        if self.result_type is None:
            return False, "Result type not set"
        
        if self.result_type == self.TYPE_MAX_SHORT_TERM:
            if self.max_values is None or self.max_total is None:
                return False, "Max short-term values not set"
            if len(self.max_values) != 11:
                return False, f"Expected 11 values, got {len(self.max_values)}"
        
        elif self.result_type == self.TYPE_ANNUAL_AVERAGE:
            if self.annual_average is None:
                return False, "Annual average not set"
        
        elif self.result_type == self.TYPE_EXCEEDANCE_TIME:
            if self.exceedance_time is None:
                return False, "Exceedance time not set"
        
        return True, "OK"
    
    def __repr__(self):
        """String representation for debugging."""
        if self.result_type == self.TYPE_MAX_SHORT_TERM:
            return (f"Result(id={self.id}, type=max_short_term, "
                    f"max={self.max_total:.3f})")
        elif self.result_type == self.TYPE_ANNUAL_AVERAGE:
            return (f"Result(id={self.id}, type=annual_average, "
                    f"value={self.annual_average:.3f})")
        elif self.result_type == self.TYPE_EXCEEDANCE_TIME:
            return (f"Result(id={self.id}, type=exceedance_time, "
                    f"time={self.exceedance_time:.1f})")
        else:
            return f"Result(id={self.id}, type=unknown)"
