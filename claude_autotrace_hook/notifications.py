from pathlib import Path
from notifypy import Notify


def _best_icon_size(available: set[int], base: int) -> int:
    """
    Try to estimate OS UI scaling via Tk's effective DPI (pixels per inch).
    96 DPI is the common "100% scale" baseline -> scale = dpi/96.
    """
    try:
        import tkinter as tk

        r = tk.Tk()
        r.withdraw()
        dpi = float(r.winfo_fpixels("1i"))
        r.destroy()
        target = int(round(base * max(1.0, dpi / 96.0)))
    except Exception:
        target = base  # If Tk/DPI isn't available, just use the base size.

    # Pick the smallest icon >= target to avoid upscaling (blurry),
    sizes = sorted(available)
    for s in sizes:
        if s >= target:
            return s

    # Fall back to the largest available if that's still not big enough
    return sizes[-1]


def send_start_notification():
    notification = Notify()
    best_size = _best_icon_size({32, 64, 128, 256}, 64)
    notification.title = "Bench is ready to go!"
    notification.message = "Claude Code is sending telemetry to Silverstream Bench."
    notification.icon = (
        Path(__file__).parent.parent / "icons" / f"ss-logo-{best_size}.png"
    )
    notification.send()
