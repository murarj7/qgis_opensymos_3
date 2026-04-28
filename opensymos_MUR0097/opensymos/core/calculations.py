"""
Module for SYMOS'97 dispersion calculations.
Contains all mathematical functions and formulas for concentration calculations.
"""
import math
import numpy as np
from qgis.core import QgsGeometry, QgsPointXY

# ============================================================================
# CONSTANTS AND TABLES
# ============================================================================

# Class stability constants for 5 stability classes
# Data from SYMOS'97 methodology
CLASS_CONSTANTS = [
    {
        'class': 1,
        'exp_p': 0.33,
        'a_y': 0.1042, 'b_y': 0.8844,
        'a_z': 0.5461, 'b_z': 0.5076,
        'k_s': 0.6, 'k_m': 184.0,
        'epsilon': 0.05
    },
    {
        'class': 2,
        'exp_p': 0.25,
        'a_y': 0.1195, 'b_y': 0.8930,
        'a_z': 0.4980, 'b_z': 0.5797,
        'k_s': 0.78, 'k_m': 200.0,
        'epsilon': 0.10
    },
    {
        'class': 3,
        'exp_p': 0.18,
        'a_y': 0.1400, 'b_y': 0.8986,
        'a_z': 0.4221, 'b_z': 0.6564,
        'k_s': 1.0, 'k_m': 236.0,
        'epsilon': 0.20
    },
    {
        'class': 4,
        'exp_p': 0.14,
        'a_y': 0.1684, 'b_y': 0.9018,
        'a_z': 0.3158, 'b_z': 0.7549,
        'k_s': 1.14, 'k_m': 300.0,
        'epsilon': 0.30
    },
    {
        'class': 5,
        'exp_p': 0.10,
        'a_y': 0.2898, 'b_y': 0.8831,
        'a_z': 0.1740, 'b_z': 0.9729,
        'k_s': 1.24, 'k_m': 411.0,
        'epsilon': 0.50
    }
]

REMOVAL_COEFFICIENTS = {
    'hydrogen_sulfide': 1.39e-5,
    'hydrogen_chloride': 1.39e-5,
    'hydrogen_peroxide': 1.39e-5,
    'dimethyl_sulfide': 1.39e-5,

    'sulfur_dioxide': 1.93e-6,
    'nitric_oxide': 1.93e-6,
    'nitrogen_dioxide': 1.93e-6,
    'ammonia': 1.93e-6,
    'carbon_disulfide': 1.93e-6,
    'formaldehyde': 1.93e-6,

    'nitrous_oxide': 1.59e-8,
    'carbon_monoxide': 1.59e-8,
    'carbon_dioxide': 1.59e-8,
    'methane': 1.59e-8,
    'higher_hydrocarbons': 1.59e-8,
    'methyl_chloride': 1.59e-8,
    'carbonyl_sulfide': 1.59e-8,

    'dust': 0.0
}

FZ_TABLE = [
    (350, 0.445), (400, 0.444), (450, 0.432), (500, 0.401),
    (550, 0.360), (600, 0.325), (650, 0.292), (700, 0.261),
    (750, 0.233), (800, 0.213), (850, 0.189), (900, 0.177),
    (950, 0.157), (1000, 0.140), (1050, 0.125), (1100, 0.111),
    (1150, 0.092), (1200, 0.078), (1250, 0.061), (1300, 0.049),
    (1350, 0.034), (1400, 0.025), (1450, 0.015), (1500, 0.007),
    (1550, 0.001), (1600, 0.000)
]

WIND_SPEED_CLASSES = {
    'slow': {'min': 0.0, 'max': 2.5, 'representative': 1.7},
    'moderate': {'min': 2.5, 'max': 7.5, 'representative': 5.0},
    'strong': {'min': 7.5, 'max': float('inf'), 'representative': 11.0}
}


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def calculate_azimuth(x1, y1, x2, y2):
    """
    Calculate azimuth from point 2 to point 1 in degrees (0-360).
    0° = North, 90° = East, etc.
    """
    dx = x1 - x2
    dy = y1 - y2
    angle_rad = math.atan2(dx, dy)
    angle_deg = math.degrees(angle_rad)
    azimuth = angle_deg % 360
    return azimuth


def angular_difference_deg(a, b):
    """
    Smallest absolute angular difference in degrees on circle 0-360.
    """
    diff = abs((a - b) % 360)
    return min(diff, 360 - diff)


def normalize_pollutant_name(pollutant):
    """
    Convert UI / free-text pollutant names to internal keys.
    """
    if pollutant is None:
        return 'dust'

    p = str(pollutant).strip().lower()

    mapping = {
        'sulfur_dioxide': 'sulfur_dioxide',
        'sulfur dioxide': 'sulfur_dioxide',
        'sulfur dioxide (so2)': 'sulfur_dioxide',
        'so2': 'sulfur_dioxide',

        'nitrogen_dioxide': 'nitrogen_dioxide',
        'nitrogen dioxide': 'nitrogen_dioxide',
        'nitrogen dioxide (no2)': 'nitrogen_dioxide',
        'no2': 'nitrogen_dioxide',

        'nitric_oxide': 'nitric_oxide',
        'nitric oxide': 'nitric_oxide',
        'nitric oxide (no)': 'nitric_oxide',
        'no': 'nitric_oxide',

        'carbon_monoxide': 'carbon_monoxide',
        'carbon monoxide': 'carbon_monoxide',
        'carbon monoxide (co)': 'carbon_monoxide',
        'co': 'carbon_monoxide',

        'dust': 'dust',
        'pm': 'dust',
        'particulates': 'dust'
    }

    return mapping.get(p, p.replace(' ', '_'))


def calculate_wind_speed_at_height(z, wind_speed_10m, exp_p):
    if z <= 10:
        return wind_speed_10m
    elif z < 200:
        return wind_speed_10m * ((z / 10.0) ** exp_p)
    else:
        return wind_speed_10m * (20.0 ** exp_p)


def calculate_sigma(x, a, b):
    return a * (x ** b)


def get_wind_direction_correction(height):
    if height <= 10:
        return 0
    else:
        return (height - 10) / 25.0


def calculate_beta_coefficient(temperature):
    if temperature >= 80:
        return 1.0
    elif temperature > 30:
        return (temperature - 30.0) / 50.0
    else:
        return 0.0


def calculate_thermal_output(volume, temperature):
    return 1e-3 * volume * 1.371 * temperature


def get_AB_constants(Q):
    if Q >= 20:
        return 30.0, 0.7
    else:
        return 90.0, 1.0 / 3.0


def calculate_fz(altitude):
    min_diff = float('inf')
    best_fz = 0.0

    for z_val, fz_val in FZ_TABLE:
        diff = abs(z_val - altitude)
        if diff < min_diff:
            min_diff = diff
            best_fz = fz_val

    return best_fz


def calculate_fz_derived(altitude, stability_class, wind_speed):
    fz = calculate_fz(altitude)

    if stability_class == 1 or stability_class == 2:
        return 2.247 * fz
    elif stability_class == 3:
        if wind_speed <= 2.5:
            return 1.170 * fz
        elif wind_speed < 7.5:
            factor = 1 - ((wind_speed - 2.5) / 5.0)
            return 1.170 * fz * factor
        else:
            return 0.0
    else:
        return 0.0


def calculate_vertical_coordinates(z_source, z_receptor, h1, receptor_height):
    z = z_receptor - z_source

    if (z + receptor_height) <= h1:
        z1 = z + receptor_height
        z2 = abs(z) + receptor_height
        z3 = z - receptor_height
    else:
        z1 = h1
        z2 = abs(z) + h1 - z
        z3 = 2.0 * z - h1

    return z1, z2, z3


def calculate_theta(x, profile, pixel_size, z_source, z_receptor):
    if z_receptor <= z_source:
        return 0.0

    profile_corrected = []
    for h in profile:
        if h > z_receptor:
            h = z_receptor
        elif h < z_source:
            h = z_source
        profile_corrected.append(h - z_source)

    area = sum(profile_corrected) * pixel_size
    theta = 0.9 * area / (x * (z_receptor - z_source))
    return max(0.0, theta)


def calculate_kh(stability_class, wind_speed, h1, z_source, z_receptor):
    if z_receptor > (z_source + h1):
        fz_h1 = calculate_fz_derived(z_source + h1, stability_class, wind_speed)
        fz_rec = calculate_fz_derived(z_receptor, stability_class, wind_speed)
        return 1 - (fz_h1 - fz_rec)
    else:
        return 1.0


def calculate_particle_settling_velocity(diameter, density):
    d = diameter * 1e-6

    rho_air = 1.3
    nu = 15e-6
    g = 9.81
    C2 = 0.8
    C3 = 0.6

    term1 = (3 * math.pi * nu) / (2 * C3 * d)
    term2 = (C2 * density * g * d) / (C3 * rho_air)

    vg = -term1 + math.sqrt(term1**2 + term2)
    return vg

def get_source_heights(source, wind_speed_10m, stability_class, distance, max_terrain_height):
    """
    Return effective source heights (h, h1).

    - Point sources and industrial area sources use plume rise calculation.
    - Line sources and passive area sources use release height only
      (no thermal plume rise).

    Returns:
        tuple: (h, h1)
    """
    if source.has_thermal_plume():
        return calculate_plume_rise(
            source, wind_speed_10m, stability_class, distance, max_terrain_height
        )

    # Non-thermal sources (line, passive area):
    # use release height directly above source terrain elevation
    h = source.release_height or 0.0

    zm = max_terrain_height - (source.z + h)

    # for non-thermal low sources, keep terrain correction simple:
    # effective height with terrain correction cannot be lower than h
    if zm > h:
        h1 = zm
    else:
        h1 = h

    return h, h1


# ============================================================================
# PLUME RISE CALCULATIONS
# ============================================================================

def calculate_plume_rise(source, wind_speed_10m, stability_class, x, max_terrain_height):
    const = CLASS_CONSTANTS[stability_class - 1]
    exp_p = const['exp_p']
    k_s = const['k_s']
    k_m = const['k_m']
    epsilon = const['epsilon']

    beta = calculate_beta_coefficient(source.gas_temperature)
    u_h = calculate_wind_speed_at_height(source.stack_height, wind_speed_10m, exp_p)
    Q = calculate_thermal_output(source.gas_volume, source.gas_temperature)
    A, B = get_AB_constants(Q)

    momentum_term = (1 - beta) * ((1.5 * source.gas_velocity * source.diameter) / u_h)
    buoyancy_term = beta * ((k_s * A * (Q ** B)) / u_h)

    if x < k_m * math.sqrt(Q):
        distance_factor = (x / (k_m * math.sqrt(Q))) ** (2.0 / 3.0)
    else:
        distance_factor = 1.0

    delta_h = (momentum_term + buoyancy_term) * distance_factor
    h = source.stack_height + delta_h

    zm = max_terrain_height - (source.z + source.stack_height)

    if zm > (1 - epsilon) * h:
        h1 = zm + epsilon * h
    else:
        h1 = h

    return h, h1


# ============================================================================
# CONCENTRATION CALCULATIONS
# ============================================================================

def calculate_concentration_point(source, receptor, stability_class, wind_speed_10m,
                                  wind_direction, distance, azimuth_source_to_receptor,
                                  max_terrain_height, terrain_profile=None,
                                  pixel_size=None, pollutant='sulfur_dioxide',
                                  is_particle=False, calculation_type='max'):
    const = CLASS_CONSTANTS[stability_class - 1]
    exp_p = const['exp_p']
    a_y = const['a_y']
    b_y = const['b_y']
    a_z = const['a_z']
    b_z = const['b_z']

    pollutant_key = normalize_pollutant_name(pollutant)

    h, h1 = get_source_heights(
        source, wind_speed_10m, stability_class, distance, max_terrain_height
    )

    # Direction correction
    if h > 10:
        fi_h = wind_direction + ((h - 10.0) / 25.0)
    else:
        fi_h = wind_direction

    if fi_h > 360:
        fi_h = fi_h - 360

    lambda_angle = abs(fi_h - azimuth_source_to_receptor)

    if lambda_angle > 90 or lambda_angle < (-90):
        lambda_angle_temp = 0.0
    else:
        lambda_angle_temp = lambda_angle

    x_l = distance * math.cos(math.radians(lambda_angle_temp))
    y_l = distance * math.sin(math.radians(lambda_angle_temp))

    if not (lambda_angle <= 20 or lambda_angle >= 340):
        return 0.0

    u_h1 = calculate_wind_speed_at_height(h1, wind_speed_10m, exp_p)

    sigma_y = calculate_sigma(x_l, a_y, b_y)
    sigma_z = calculate_sigma(x_l, a_z, b_z)

    ku = REMOVAL_COEFFICIENTS.get(pollutant_key, 0.0)

    if terrain_profile is not None and pixel_size is not None:
        theta = calculate_theta(distance, terrain_profile, pixel_size, source.z, receptor.z)
    else:
        theta = 0.0

    kh = calculate_kh(stability_class, wind_speed_10m, h1, source.z, receptor.z)

    z1, z2, z3 = calculate_vertical_coordinates(
        source.z, receptor.z, h1, receptor.height_above
    )

    if source.has_thermal_plume():
        base = (1e6 * source.emission) / (
            (2 * math.pi * sigma_y * sigma_z * u_h1) + source.gas_volume
        )
    else:
        base = (1e6 * source.emission) / (
            2 * math.pi * sigma_y * sigma_z * u_h1
        )

    crosswind = math.exp(-(y_l ** 2) / (2 * sigma_y ** 2))
    removal = math.exp(-ku * (x_l / u_h1))

    if not is_particle:
        vertical_term1 = math.exp(-((z1 - h1) ** 2) / (2 * sigma_z ** 2))
        vertical_term2 = (1 - theta) * math.exp(-((z2 + h1) ** 2) / (2 * sigma_z ** 2))
        vertical_term3 = theta * math.exp(-((z3 - h1) ** 2) / (2 * sigma_z ** 2))

        vertical = vertical_term1 + vertical_term2 + vertical_term3
        concentration = base * crosswind * removal * kh * vertical
    else:
        particle_sum = 0.0
        for diameter, density, percentage in source.particle_data:
            vg = calculate_particle_settling_velocity(diameter, density)
            h_gi = (x_l * vg) / u_h1

            term1 = math.exp(-((z1 - (h1 - h_gi)) ** 2) / (2 * sigma_z ** 2))
            term2 = (1 - theta) * math.exp(-((z2 + h1 + h_gi) ** 2) / (2 * sigma_z ** 2))
            term3 = theta * math.exp(-((z3 + (h1 + h_gi)) ** 2) / (2 * sigma_z ** 2))
            particle_sum += (percentage / 100.0) * (term1 + term2 + term3)

        concentration = base * crosswind * kh * particle_sum

    return max(0.0, concentration)


# ============================================================================
# AGGREGATION FUNCTIONS
# ============================================================================

def get_wind_speed_classes_for_stability(stability_class, calculation_type='max'):
    if calculation_type == 'max':
        if stability_class == 1:
            return [1.7]
        elif stability_class == 2:
            return [1.7, 5.0]
        elif stability_class == 3:
            return [1.7, 5.0, 11.0]
        elif stability_class == 4:
            return [1.7, 5.0, 11.0]
        elif stability_class == 5:
            return [1.7, 5.0]
    else:
        if stability_class == 1:
            return [1.7]
        elif stability_class == 2:
            return [1.7, 5.0]
        elif stability_class == 3:
            return [1.7, 5.0, 11.0]
        elif stability_class == 4:
            return [1.7, 5.0, 11.0]
        elif stability_class == 5:
            return [1.7, 5.0]

    return []


if __name__ == "__main__":
    print("SYMOS'97 Calculations Module")
    print("\nTesting basic functions:")

    az = calculate_azimuth(100, 100, 0, 0)
    print(f"Azimuth (0,0)->(100,100): {az:.1f}°")

    u = calculate_wind_speed_at_height(50, 5.0, 0.2)
    print(f"Wind at 50m (5m/s at 10m): {u:.2f} m/s")

    print("\nNote: Full calculation requires Source object with parameters")