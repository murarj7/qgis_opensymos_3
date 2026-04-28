import numpy as np
from osgeo import gdal
from qgis.core import QgsRasterLayer


class Terrain:
    def __init__(self, raster_layer):
        if not raster_layer or not isinstance(raster_layer, QgsRasterLayer):
            raise ValueError("Invalid raster layer")

        self.layer = raster_layer
        self.extent = raster_layer.extent()

        self.width = raster_layer.width()
        self.height = raster_layer.height()

        self.pixel_width = raster_layer.rasterUnitsPerPixelX()
        self.pixel_height = raster_layer.rasterUnitsPerPixelY()

        # VZOR uses pixel width as hrana_pixel
        self.pixel_size = self.pixel_width

        self._raster_array = None
        self._gdal_ds = None

        source_path = raster_layer.source()
        self._gdal_ds = gdal.Open(source_path)
        if self._gdal_ds is None:
            raise ValueError(f"Cannot open raster with GDAL: {source_path}")

        gt = self._gdal_ds.GetGeoTransform()
        self.raster_tlx = gt[0]
        self.raster_tly = gt[3]
        self.gdal_pixel_width = gt[1]
        self.gdal_pixel_height = gt[5]

    def _load_raster_array(self):
        if self._raster_array is not None:
            return

        band = self._gdal_ds.GetRasterBand(1)
        arr = band.ReadAsArray(
            0,
            0,
            self._gdal_ds.RasterXSize,
            self._gdal_ds.RasterYSize
        )

        if arr is None:
            raise ValueError("GDAL ReadAsArray failed")

        self._raster_array = np.array(arr, dtype=float)

    def get_elevation(self, x, y):
        """
        VZOR-like single-point elevation using pixel index truncation.
        Returns None if outside raster.
        """
        self._load_raster_array()

        try:
            x_pixel = int((x - self.raster_tlx) / self.gdal_pixel_width)
            y_pixel = int((y - self.raster_tly) / self.gdal_pixel_height)

            if x_pixel < 0 or x_pixel >= self._raster_array.shape[1]:
                return None
            if y_pixel < 0 or y_pixel >= self._raster_array.shape[0]:
                return None

            z = self._raster_array[y_pixel, x_pixel]
            if np.isnan(z):
                return None

            return float(z)
        except Exception:
            return None

    def _diag_rect_mn(self, matrix, step_v):
        """
        Approximate diagonal for rectangular matrix with more rows than columns.
        Mirrors VZOR diag_obdelnik_mn.
        """
        diag = []
        m = 0

        for n in range(0, matrix.shape[1]):
            for _ in range(0, step_v):
                if matrix.shape[0] - m == 0:
                    break
                diag.append(float(matrix[m, n]))
                m += 1

        return diag

    def _diag_rect_nm(self, matrix, step_h):
        """
        Approximate diagonal for rectangular matrix with more columns than rows.
        Mirrors VZOR diag_obdelnik_nm.
        """
        diag = []
        n = 0

        for m in range(0, matrix.shape[0]):
            for _ in range(0, step_h):
                if matrix.shape[1] - n == 0:
                    break
                diag.append(float(matrix[m, n]))
                n += 1

        return diag

    def get_profile(self, x1, y1, x2, y2):
        """
        Return VZOR-like terrain profile between two points.

        Important:
        - this is NOT true line sampling
        - this follows original raster submatrix + pseudo-diagonal logic
        """
        self._load_raster_array()

        try:
            # VZOR-like pixel indices
            m1 = abs(int((self.raster_tly - y1) / self.gdal_pixel_width))
            n1 = abs(int((self.raster_tlx - x1) / self.gdal_pixel_width))
            m2 = abs(int((self.raster_tly - y2) / self.gdal_pixel_width))
            n2 = abs(int((self.raster_tlx - x2) / self.gdal_pixel_width))

            if not (0 <= m1 < self._raster_array.shape[0] and 0 <= n1 < self._raster_array.shape[1]):
                return None
            if not (0 <= m2 < self._raster_array.shape[0] and 0 <= n2 < self._raster_array.shape[1]):
                return None

            first_row = min(m1, m2)
            last_row = max(m1, m2)
            first_col = min(n1, n2)
            last_col = max(n1, n2)

            matrix = self._raster_array[first_row:last_row + 1, first_col:last_col + 1].copy()

            # Mirror original VZOR orientation rule
            if ((first_row == m1 and first_col == n2) or
                    (first_row == m2 and first_col == n1)):
                matrix = matrix[::-1]

            # VZOR special cases
            if m1 == m2 and n1 == n2:
                diag = [0.0]
            elif abs(m1 - m2) == 1 or abs(n1 - n2) == 1:
                diag = [0.0]
            else:
                rows, cols = matrix.shape

                if rows == cols:
                    diag = [float(v) for v in np.diag(matrix)]
                elif rows > cols:
                    step_v = int(round(float(rows) / cols))
                    diag = self._diag_rect_mn(matrix, step_v)
                else:
                    step_h = int(round(float(cols) / rows))
                    diag = self._diag_rect_nm(matrix, step_h)

            if diag is None:
                return None

            diag = list(diag)

            if len(diag) > 2:
                diag = diag[1:-1]
            elif len(diag) <= 2:
                diag = [0.0]

            return diag

        except Exception:
            return None

    def get_max_height_from_profile(self, profile):
        if not profile:
            return None

        vals = [v for v in profile if v is not None and not np.isnan(v)]
        if not vals:
            return None

        return float(max(vals))

    def get_profile_and_max_height(self, x1, y1, x2, y2):
        """
        Returns:
            (profile_for_theta, max_height_for_h1)
        """
        profile = self.get_profile(x1, y1, x2, y2)
        if profile is None:
            return None, None

        max_height = self.get_max_height_from_profile(profile)
        return profile, max_height

    def clear_cache(self):
        self._raster_array = None

    def get_stats(self):
        return {
            "width": self.width,
            "height": self.height,
            "pixel_size": self.pixel_size,
            "extent": self.extent.toString(),
            "crs": self.layer.crs().authid(),
        }