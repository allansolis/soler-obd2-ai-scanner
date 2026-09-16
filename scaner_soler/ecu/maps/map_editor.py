from .map_table import MapTable, SafetyError


class MapEditor:
    """
    High-level editor for MapTable objects.
    All mutations go through here so change history is tracked centrally.
    """

    def __init__(self, table: MapTable):
        self.table = table

    # ── Single cell ────────────────────────────────────────────────────────

    def set(self, rpm_idx: int, load_idx: int, value: float):
        self.table.set_cell(rpm_idx, load_idx, value)

    def add(self, rpm_idx: int, load_idx: int, delta: float):
        current = self.table.get_cell(rpm_idx, load_idx)
        self.table.set_cell(rpm_idx, load_idx, current + delta)

    # ── Region operations ──────────────────────────────────────────────────

    def add_to_region(self, rpm_slice: slice, load_slice: slice, delta: float):
        self.table.set_region(rpm_slice, load_slice, delta)

    def add_to_all(self, delta: float):
        self.add_to_region(slice(None), slice(None), delta)

    def add_to_high_load(self, threshold_pct: float, delta: float):
        """Add delta to all cells where load > threshold_pct."""
        load_start = next(
            (i for i, v in enumerate(self.table.load_axis) if v >= threshold_pct),
            len(self.table.load_axis)
        )
        self.add_to_region(slice(None), slice(load_start, None), delta)

    def add_to_high_rpm(self, threshold_rpm: float, delta: float):
        rpm_start = next(
            (i for i, v in enumerate(self.table.rpm_axis) if v >= threshold_rpm),
            len(self.table.rpm_axis)
        )
        self.add_to_region(slice(rpm_start, None), slice(None), delta)

    # ── Smoothing ──────────────────────────────────────────────────────────

    def smooth_region(self, rpm_slice: slice, load_slice: slice):
        """Simple 3x3 box blur on a region (helps with dyno-pulled maps)."""
        import numpy as np
        from scipy.ndimage import uniform_filter
        region = self.table.values[rpm_slice, load_slice].copy()
        smoothed = uniform_filter(region, size=3, mode="nearest")
        # Apply smoothed values with safety check
        ri = list(range(*rpm_slice.indices(len(self.table.rpm_axis))))
        li = list(range(*load_slice.indices(len(self.table.load_axis))))
        for i, ridx in enumerate(ri):
            for j, lidx in enumerate(li):
                try:
                    self.table.set_cell(ridx, lidx, float(smoothed[i, j]))
                except SafetyError:
                    pass  # keep original if smoothed value is unsafe

    # ── Undo / restore ─────────────────────────────────────────────────────

    def restore(self):
        self.table.restore_backup()

    def changes_summary(self) -> str:
        log = self.table.changed_cells
        if not log:
            return "Sin cambios."
        lines = [f"{'RPM':>6}  {'Load':>6}  {'Antes':>8}  {'Despues':>8}  {'Delta':>8}"]
        for c in log:
            delta = c["new"] - c["old"]
            lines.append(
                f"{c['rpm']:6.0f}  {c['load']:6.1f}  {c['old']:8.3f}  {c['new']:8.3f}  {delta:+8.3f}"
            )
        return "\n".join(lines)
