import plotly.graph_objs as go
import numpy as np

# -----------------------------------------------------------
# Add and annotate traces
# -----------------------------------------------------------

def add_trace(figure, x, y, name, hovertemplate=""): 
    """
    Add trace to figure.
    """
    figure.add_trace(
        go.Scatter(
            x=x,
            y=y,
            mode="lines",
            name=name,
            line=dict(color="rgba(180,180,180,0.7)", width=1.5, shape="spline"),
            marker=dict(size=3),
            hovertemplate=hovertemplate,
        )
    )

def add_mean_trace(figure, x, y, name, showmarkers=False, hovertemplate=""): 
    """
    Add mean trace to figure.
    """
    figure.add_trace(
            go.Scatter(
                x=x,
                y=y,
                mode="lines+markers" if showmarkers else "lines",
                name=name,
                line=dict(
                    color="rgba(38,139,210,0.9)",
                    width=3,
                    shape="spline",
                ),
                hovertemplate=hovertemplate,
            )
        )

def annotate_minmax_on_series(fig, x, y, unit, label_prefix=""):
    """
    Add text labels for min and max along a given series, and return (min_val, max_val).
    """
    y_arr = np.asarray(y)
    if y_arr.size == 0:
        return None, None

    idx_min = int(y_arr.argmin())
    idx_max = int(y_arr.argmax())
    min_val = float(y_arr[idx_min])
    max_val = float(y_arr[idx_max])
    x_min = x[idx_min]
    x_max = x[idx_max]

    # Min annotation
    if idx_min <= len(y_arr) / 10:
        shift_min_x = 40
    else:
        shift_min_x = -40
    fig.add_annotation(
        x=x_min,
        y=min_val,
        xref="x",
        yref="y",
        text=f"{label_prefix}min {min_val:.1f}º{unit}",
        showarrow=True,
        arrowhead=2,
        ax=shift_min_x,
        ay=30,
        font=dict(color="rgba(38,139,210,1.0)", size=13),
        arrowcolor="rgba(38,139,210,0.9)",
    )

    # Max annotation
    if idx_max >= len(y_arr) * 0.9:
        shift_max_x = -40
    else:
        shift_max_x = 40
    fig.add_annotation(
        x=x_max,
        y=max_val,
        xref="x",
        yref="y",
        text=f"{label_prefix}max {max_val:.1f}º{unit}",
        showarrow=True,
        arrowhead=2,
        ax=shift_max_x,
        ay=-30,
        font=dict(color="rgba(220,50,47,1.0)", size=13),
        arrowcolor="rgba(220,50,47,0.9)",
    )
    
    return min_val, max_val

