import numpy as np

try:
    import matplotlib.pyplot as plt
    from matplotlib import cm
    HAS_MPL = True
except ImportError:
    HAS_MPL = False


def _require_mpl():
    if not HAS_MPL:
        raise ImportError("matplotlib is required for visualization: pip install matplotlib")


def plot_3d(table, highlight_changes: bool = True, title: str | None = None):
    _require_mpl()
    from ..maps.map_table import MapTable
    fig = plt.figure(figsize=(13, 7))
    ax = fig.add_subplot(111, projection="3d")
    X, Y = np.meshgrid(table.load_axis, table.rpm_axis)
    Z = table.values

    if highlight_changes and table.has_changes:
        colors = np.zeros((*Z.shape, 4))
        diff = table.diff
        norm = np.abs(diff).max() or 1.0
        for i in range(Z.shape[0]):
            for j in range(Z.shape[1]):
                if diff[i, j] != 0:
                    ratio = abs(diff[i, j]) / norm
                    colors[i, j] = (1.0, 0.3 * (1 - ratio), 0.0, 0.9)  # orange→red
                else:
                    colors[i, j] = (0.2, 0.5, 0.9, 0.7)               # blue
        ax.plot_surface(X, Y, Z, facecolors=colors, shade=True)
    else:
        surf = ax.plot_surface(X, Y, Z, cmap=cm.RdYlGn, alpha=0.85)
        fig.colorbar(surf, ax=ax, shrink=0.5, label=table.unit)

    ax.set_xlabel("Carga (%)")
    ax.set_ylabel("RPM")
    ax.set_zlabel(table.unit or "Valor")
    ax.set_title(title or f"Mapa: {table.name}")
    plt.tight_layout()
    plt.show()
    return fig


def plot_heatmap(table, show_diff: bool = False, title: str | None = None):
    _require_mpl()
    fig, ax = plt.subplots(figsize=(12, 6))
    data = table.diff if show_diff else table.values
    cmap = "RdBu_r" if show_diff else "RdYlGn"
    vmax = np.abs(data).max() if show_diff else None
    vmin = -vmax if show_diff else None
    im = ax.imshow(data, aspect="auto", origin="lower", cmap=cmap, vmin=vmin, vmax=vmax)
    ax.set_xticks(range(len(table.load_axis)))
    ax.set_xticklabels([f"{v:.0f}" for v in table.load_axis], fontsize=7, rotation=45)
    ax.set_yticks(range(len(table.rpm_axis)))
    ax.set_yticklabels([f"{v:.0f}" for v in table.rpm_axis], fontsize=7)
    ax.set_xlabel("Carga (%)")
    ax.set_ylabel("RPM")
    label = ("Diferencia " if show_diff else "") + (table.unit or "Valor")
    plt.colorbar(im, ax=ax, label=label)
    ax.set_title(title or (f"Diferencia — {table.name}" if show_diff else f"Mapa — {table.name}"))
    for i in range(data.shape[0]):
        for j in range(data.shape[1]):
            ax.text(j, i, f"{data[i,j]:.1f}", ha="center", va="center", fontsize=5, color="black")
    plt.tight_layout()
    plt.show()
    return fig


def plot_usage_heatmap(rpm_samples: list, load_samples: list, rpm_axis: list, load_axis: list):
    """Show which cells the engine visited most during a track session."""
    _require_mpl()
    import pandas as pd
    rpm_bins = pd.cut(rpm_samples, bins=rpm_axis, labels=[f"{v:.0f}" for v in rpm_axis[:-1]])
    load_bins = pd.cut(load_samples, bins=load_axis, labels=[f"{v:.0f}" for v in load_axis[:-1]])
    df = pd.DataFrame({"rpm": rpm_bins, "load": load_bins})
    heat = df.groupby(["rpm", "load"]).size().unstack(fill_value=0)
    fig, ax = plt.subplots(figsize=(12, 6))
    im = ax.imshow(heat.values, aspect="auto", origin="lower", cmap="hot_r")
    ax.set_xlabel("Carga (%)")
    ax.set_ylabel("RPM")
    ax.set_title("Mapa de uso — celdas visitadas en pista")
    plt.colorbar(im, ax=ax, label="Muestras")
    plt.tight_layout()
    plt.show()
    return fig
