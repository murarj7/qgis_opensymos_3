"""
Module for source representation in SYMOS dispersion model.
Each source (point, line, area) is represented by a Source object.
"""
from qgis.core import QgsGeometry, QgsPointXY
import math

class Source:
    """
    Represents a single pollution source.
    
    Point sources (stacks) require all stack parameters.
    Line and area sources require only basic parameters, but can be
    extended with industrial parameters if needed (for industrial areas
    with thermal processes).
    
    Missing optional parameters can be replaced by default values
    with appropriate warnings.
    """
    
    # Default values for missing parameters
    DEFAULTS = {
        'point': {
            'stack_height': 15.0,        # meters - average industrial stack
            'gas_temperature': 80.0,      # °C - assumed heated exhaust
            'diameter': 0.5,              # meters - typical small stack
            'gas_velocity': 8.0,          # m/s - typical exit velocity
            # gas_volume has NO default - must be provided
        },
        'line': {
            'release_height': 1.5,        # meters - typical vehicle exhaust height
        },
        'area': {
            'release_height': 2.0,         # meters - typical for passive areas
            # industrial areas may have stack parameters instead
        }
    }
    
    def __init__(self, source_id, geometry, source_type):
        """
        Initialize a source with basic information from vector layer.
        
        Args:
            source_id: int/str - unique identifier from attribute table
            geometry: QgsGeometry - feature geometry
            source_type: str - 'point', 'line', or 'area'
        """
        self.id = source_id
        self.geom = geometry
        self.type = source_type
        
        # Get coordinates (point geometry or centroid for line/area)
        self._set_coordinates(geometry)
        
        # Common attributes (will be set later)
        self.z = None                # Elevation from DEM [m]
        self.emission = None         # M [g/s] - for area sources: total emission / number of points
        self.annual_utilization = 1.0  # α (0-1), default = full operation
        
        # Release height (for line and passive area sources)
        self.release_height = None   # Height above ground [m]
        
        # Stack parameters (for point sources and industrial areas)
        self.stack_height = None     # H [m]
        self.gas_temperature = None  # ts [°C]
        self.diameter = None         # d [m]
        self.gas_velocity = None     # wo [m/s]
        self.gas_volume = None       # Vs [m³/s]
        
        # Flag for industrial sources (if any stack parameter is provided)
        self.is_industrial = False
        
        # Line source attributes
        self.length = None           # [m] (calculated from geometry)
        
        # Area source attributes
        self.area = None             # [m²] (calculated from geometry)
        
        # Particle data (for dust)
        self.particle_data = []      # list of (diameter [µm], density [kg/m³], percentage [%])
        
        # Segment data (for line sources after splitting)
        self.segment_id = None
        self.segment_start = None    # (x, y) tuple
        self.segment_end = None      # (x, y) tuple
        self.segment_length = None    # [m]
        
        # Track which default values were used
        self.fallbacks_used = []
    
    def _set_coordinates(self, geometry):
        """
        Extract coordinates from geometry.
        For line/area, uses centroid as representative point.
        """
        if geometry.type() == 0:  # Point
            point = geometry.asPoint()
            self.x = point.x()
            self.y = point.y()
        else:
            # For line/area, use centroid for calculations
            centroid = geometry.centroid().asPoint()
            self.x = centroid.x()
            self.y = centroid.y()
    
    def set_elevation(self, z):
        """
        Set elevation from DEM.
        
        Args:
            z: float - elevation in meters
        """
        self.z = z
    
    def set_emission_params(self, emission, utilization=1.0):
        """
        Set basic emission parameters.
        
        Args:
            emission: float - M [g/s]
            utilization: float - α (0-1), default 1.0 = full time operation
        """
        self.emission = emission
        self.annual_utilization = utilization
    
    def set_release_height(self, height):
        """
        Set release height above ground (for line and passive area sources).
        
        Args:
            height: float - release height [m]
        """
        self.release_height = height
    
    def set_stack_params(self, height=None, temperature=None, diameter=None, 
                        velocity=None, volume=None):
        """
        Set stack parameters (for point sources and industrial areas).
        When any of these is set, source is marked as industrial.
        Missing parameters will be filled with defaults during validation.
        
        Args:
            height: float - stack height H [m] (optional)
            temperature: float - gas temperature ts [°C] (optional)
            diameter: float - stack inner diameter d [m] (optional)
            velocity: float - exit velocity wo [m/s] (optional)
            volume: float - gas volume flow Vs [m³/s] (REQUIRED for point sources)
        """
        self.stack_height = height
        self.gas_temperature = temperature
        self.diameter = diameter
        self.gas_velocity = velocity
        self.gas_volume = volume
        
        # Mark as industrial if any stack parameter is provided
        if any(v is not None for v in [height, temperature, diameter, velocity, volume]):
            self.is_industrial = True
    
    def set_line_params(self):
        """
        Set line source parameters.
        
        """
        self.length = self.geom.length()
    
    def set_area_params(self):
        """
        Set area source parameters.
        """
        self.area = self.geom.area()
    
    def add_particle_fraction(self, diameter, density, percentage):
        """
        Add a particle size fraction (for dust).
        
        Args:
            diameter: float - particle diameter [µm]
            density: float - particle density [kg/m³]
            percentage: float - percentage of total mass [%]
        """
        self.particle_data.append((diameter, density, percentage))
    
    def set_segment_data(self, segment_id, start_point, end_point, segment_length):
        """
        Set data for a specific segment after line splitting.
        
        Args:
            segment_id: int - identifier of the segment
            start_point: QgsPointXY - start coordinates
            end_point: QgsPointXY - end coordinates
            segment_length: float - length of this segment [m]
        """
        self.segment_id = segment_id
        self.segment_start = (start_point.x(), start_point.y())
        self.segment_end = (end_point.x(), end_point.y())
        self.segment_length = segment_length
    
    def has_thermal_plume(self):
        """
        Check if source should be modeled with thermal plume rise.
        
        Returns:
            bool: True if source has stack parameters and is industrial
        """
        if self.type == 'point':
            return True  # All point sources have thermal plume (even cold ones)
        else:
            # Line and area sources have thermal plume only if explicitly marked
            return self.is_industrial
    
    def get_effective_height(self):
        """
        Get effective source height (without plume rise).
        For point sources: stack height
        For others: release height
        
        Returns:
            float: effective height [m]
        """
        if self.type == 'point':
            return self.stack_height or 0
        else:
            return self.release_height or 0
    
    def validate_with_fallback(self):
        """
        Validate source parameters, using fallback values for missing data.
        
        Returns:
            tuple: (is_valid, warnings, fallbacks_used)
                   is_valid: bool - False if critical data missing
                   warnings: list of warning messages
                   fallbacks_used: list of parameters replaced with defaults
        """
        warnings = []
        fallbacks = []
        
        # Critical checks
        if self.z is None:
            return False, ["Elevation (z) not set - cannot determine source height"], []
        
        if self.emission is None:
            return False, ["Emission rate not set - cannot calculate concentrations"], []
        
        # Type-specific validation with fallbacks
        if self.type == 'point':
            # Gas volume is critical - cannot be defaulted
            if self.gas_volume is None:
                return False, ["Gas volume (Vs) must be provided for point sources"], []
            
            # Stack height fallback
            if self.stack_height is None:
                self.stack_height = self.DEFAULTS['point']['stack_height']
                fallbacks.append("stack_height")
                warnings.append(f"Stack height not provided, using default {self.DEFAULTS['point']['stack_height']} m")
            
            # Temperature fallback
            if self.gas_temperature is None:
                self.gas_temperature = self.DEFAULTS['point']['gas_temperature']
                fallbacks.append("gas_temperature")
                warnings.append(f"Gas temperature not provided, using default {self.DEFAULTS['point']['gas_temperature']} °C")
            
            # Diameter fallback
            if self.diameter is None:
                self.diameter = self.DEFAULTS['point']['diameter']
                fallbacks.append("diameter")
                warnings.append(f"Stack diameter not provided, using default {self.DEFAULTS['point']['diameter']} m")
            
            # Velocity fallback
            if self.gas_velocity is None:
                self.gas_velocity = self.DEFAULTS['point']['gas_velocity']
                fallbacks.append("gas_velocity")
                warnings.append(f"Exit velocity not provided, using default {self.DEFAULTS['point']['gas_velocity']} m/s")
        
        elif self.type == 'line':
            # Release height fallback
            if self.release_height is None:
                self.release_height = self.DEFAULTS['line']['release_height']
                fallbacks.append("release_height")
                warnings.append(f"Release height not provided, using default {self.DEFAULTS['line']['release_height']} m")
            
        elif self.type == 'area':
            # For industrial areas, we need either release_height OR stack parameters
            if self.is_industrial:
                # Industrial area - check stack parameters with fallbacks
                if self.stack_height is None:
                    self.stack_height = self.DEFAULTS['point']['stack_height']
                    fallbacks.append("stack_height")
                    warnings.append(f"Stack height not provided for industrial area, using default {self.DEFAULTS['point']['stack_height']} m")
                
                if self.gas_temperature is None:
                    self.gas_temperature = self.DEFAULTS['point']['gas_temperature']
                    fallbacks.append("gas_temperature")
                    warnings.append(f"Gas temperature not provided for industrial area, using default {self.DEFAULTS['point']['gas_temperature']} °C")
                
                if self.diameter is None:
                    self.diameter = self.DEFAULTS['point']['diameter']
                    fallbacks.append("diameter")
                    warnings.append(f"Stack diameter not provided for industrial area, using default {self.DEFAULTS['point']['diameter']} m")
                
                if self.gas_velocity is None:
                    self.gas_velocity = self.DEFAULTS['point']['gas_velocity']
                    fallbacks.append("gas_velocity")
                    warnings.append(f"Exit velocity not provided for industrial area, using default {self.DEFAULTS['point']['gas_velocity']} m/s")
                
                # Gas volume is still required for industrial areas
                if self.gas_volume is None:
                    return False, ["Gas volume (Vs) must be provided for industrial area sources"], []
            
            else:
                # Passive area - release height fallback
                if self.release_height is None:
                    self.release_height = self.DEFAULTS['area']['release_height']
                    fallbacks.append("release_height")
                    warnings.append(f"Release height not provided, using default {self.DEFAULTS['area']['release_height']} m")
        
        self.fallbacks_used = fallbacks
        return True, warnings, fallbacks
    
    def get_warning_message(self):
        """
        Get formatted warning message about used fallbacks.
        
        Returns:
            str: formatted warning message or empty string if no fallbacks used
        """
        if not self.fallbacks_used:
            return ""
        
        msg = f"Source {self.id} ({self.type}) is missing some parameters:\n"
        for param in self.fallbacks_used:
            if self.type == 'point' or (self.type == 'area' and self.is_industrial):
                if param in self.DEFAULTS['point']:
                    msg += f"  • {param} = {self.DEFAULTS['point'][param]} (default)\n"
            else:
                if param in self.DEFAULTS.get(self.type, {}):
                    msg += f"  • {param} = {self.DEFAULTS[self.type][param]} (default)\n"
        
        msg += "\nThis may affect calculation accuracy."
        return msg
    
    def __repr__(self):
        """String representation for debugging."""
        fallback_info = f", fallbacks={self.fallbacks_used}" if self.fallbacks_used else ""
        return (f"Source(id={self.id}, type={self.type}, "
                f"industrial={self.is_industrial}{fallback_info}, "
                f"x={self.x:.1f}, y={self.y:.1f})")

