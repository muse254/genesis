"""Degradation ladder: how much insult does the fingerprint survive?

Resizes and re-encodes like a publishing platform and records the PCE after each step.
"""

from __future__ import annotations

import numpy as np

from fingerprint import prnu

#: The ladder run for `docs/gates.md`: (longest edge in pixels, JPEG quality).
DEFAULT_STEPS = (
    (6000, 95),
    (6000, 80),
    (4000, 80),
    (3000, 80),
    (2400, 80),
    (1800, 95),
    (1800, 80),
    (1200, 80),
)


def develop(path):
    """Develop a RAW; auto-brightness off so the ladder measures compression, not tone."""
    import rawpy
    from PIL import Image

    with rawpy.imread(str(path)) as raw:
        return Image.fromarray(raw.postprocess(no_auto_bright=True, output_bps=8))


def to_web_jpeg(image, longest_edge: int = 1800, quality: int = 80, path=None):
    """Lanczos down to ``longest_edge``, then JPEG at ``quality``.

    Quality dominates: on the R10, 1800px q95 scores 408, q80 scores 37 (the null).

    Parameters
    ----------
    image : PIL.Image.Image | str | Path
        A developed image, or a RAW path to develop first.
    longest_edge : int
        Target for the longer side. ``None`` leaves the size alone.
    quality : int
        JPEG quality.
    path : str | Path, optional
        Where to write. A temporary file is used when omitted.

    Returns
    -------
    PIL.Image.Image
        The image as re-read from the encoded JPEG.
    """
    import tempfile

    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    if not hasattr(image, "resize"):
        image = develop(image)

    if longest_edge is not None and max(image.size) != longest_edge:
        scale = longest_edge / max(image.size)
        size = (round(image.size[0] * scale), round(image.size[1] * scale))
        image = image.resize(size, Image.LANCZOS)

    if path is None:
        path = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False).name
    image.save(path, "JPEG", quality=quality)

    with Image.open(path) as reread:
        return reread.copy()


def strip_uniform_border(image, tolerance: float = 2.0, max_fraction: float = 0.25):
    """Remove a flat added margin, returning the photograph inside it.

    Padding changes aspect ratio, so the scale search cannot find K through
    it (a 200px margin took a real file from 90,846 to 37.9). Conservative:
    lines must be flat within `tolerance` (0-255 levels), at most
    `max_fraction` per side, and all four sides must agree. Otherwise unchanged.
    """
    import numpy as np
    from PIL import Image

    grey = np.asarray(image.convert("L"), dtype=np.float32)
    height, width = grey.shape
    limit_v, limit_h = int(height * max_fraction), int(width * max_fraction)

    def run(lines) -> int:
        count = 0
        for line in lines:
            if line.std() > tolerance:
                break
            count += 1
        return count

    top = min(run(grey[i] for i in range(limit_v)), limit_v)
    bottom = min(run(grey[height - 1 - i] for i in range(limit_v)), limit_v)
    left = min(run(grey[:, i] for i in range(limit_h)), limit_h)
    right = min(run(grey[:, width - 1 - i] for i in range(limit_h)), limit_h)

    # All four sides, or it is scene content (e.g. a blown sky).
    if min(top, bottom, left, right) == 0:
        return image

    box = (left, top, width - right, height - bottom)
    if box[2] - box[0] < width // 2 or box[3] - box[1] < height // 2:
        return image

    return image.crop(box)


def green_channel(image):
    """The green channel of a delivered image, in [0, 1].

    Green has the most photosites; luminance measured at the null where green scored 408.
    """
    return np.asarray(image, dtype=np.float32)[:, :, 1] / 255.0


def ladder(image, reference, steps=None):
    """Run the degradation ladder and return [(label, pce, scale, orientation), ...].

    Parameters
    ----------
    image : PIL.Image.Image | str | Path
        A developed image, or a RAW path.
    reference : dict[int, np.ndarray] | np.ndarray
        An enrolled fingerprint; per-plane ones are collapsed with :func:`prnu.sensor_field`.
    steps : sequence[tuple[int, int]], optional
        ``(longest_edge, quality)`` pairs. Defaults to :data:`DEFAULT_STEPS`.
    """
    if not hasattr(image, "resize"):
        image = develop(image)
    if isinstance(reference, dict):
        reference = prnu.sensor_field(reference)

    results = []
    for edge, quality in steps or DEFAULT_STEPS:
        probe = green_channel(to_web_jpeg(image, longest_edge=edge, quality=quality))
        residual = prnu.noise_residual(probe)
        match = prnu.crop_and_scale_search(residual, reference)
        results.append((f"{edge}px q{quality}", match.pce, match.scale, match.orientation))
    return results
