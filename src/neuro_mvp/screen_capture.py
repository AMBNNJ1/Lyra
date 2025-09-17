import os
import sys
import base64
import tempfile
import subprocess
from typing import Optional, Tuple


def _tmp_png(prefix: str = "screen_") -> str:
    d = os.path.join(os.getcwd(), ".data")
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        d = tempfile.gettempdir()
    fd, path = tempfile.mkstemp(prefix=prefix, suffix=".png", dir=d)
    os.close(fd)
    return path


def capture_screenshot(out_path: Optional[str] = None) -> str:
    """Capture the primary screen to a PNG file.

    Tries mss -> PIL.ImageGrab -> PowerShell .NET fallback on Windows.
    Returns the saved file path.
    """
    out = out_path or _tmp_png()

    # mss path
    try:
        import mss  # type: ignore
        import mss.tools  # type: ignore
        with mss.mss() as sct:
            monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            img = sct.grab(monitor)
            mss.tools.to_png(img.rgb, img.size, output=out)
        return out
    except Exception:
        pass

    # PIL path
    try:
        from PIL import ImageGrab  # type: ignore
        img = ImageGrab.grab()  # type: ignore[attr-defined]
        img.save(out, format="PNG")
        return out
    except Exception:
        pass

    # PowerShell .NET fallback (Windows)
    if os.name == "nt":
        ps = r'''
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bmp = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
$gfx = [System.Drawing.Graphics]::FromImage($bmp)
$gfx.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
$bmp.Save("{OUT}",[System.Drawing.Imaging.ImageFormat]::Png)
$gfx.Dispose(); $bmp.Dispose()
'''.replace("{OUT}", out.replace("\\", "/"))
        try:
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
            if os.path.exists(out):
                return out
        except Exception:
            pass

    raise RuntimeError("screenshot failed: no capture backend available")


def image_file_to_data_url(path: str) -> str:
    """Return a data: URL for the image (PNG). Useful for OpenAI-compatible VLMs."""
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:image/png;base64,{b64}"

