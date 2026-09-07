"""Degradation ladder: how much insult does the fingerprint survive?

Applies each transform a published image actually undergoes -- resize, JPEG
re-encode at descending quality, crop, mild sharpening, a social-platform
round trip -- and records the PCE after each.

This produces the evidence behind the retroactive claim. Gate B (BUILD.md
sec.9) is one row of this table promoted to a go/no-go decision.
"""

from __future__ import annotations

import numpy as np

from fingerprint import prnu

#: The ladder run for `docs/gates.md`: (longest edge in pixels, JPEG quality).
#: Native resolution first, then the sizes a photo-sharing site actually
#: serves, at a good and a mean quality setting.
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
    """Render a RAW the way a photographer would before publishing it.

    Demosaic, white balance and gamma, with auto-brightness off so the ladder
    measures the compression rather than a tone change.
    """
    import rawpy
    from PIL import Image

    with rawpy.imread(str(path)) as raw:
        return Image.fromarray(raw.postprocess(no_auto_bright=True, output_bps=8))


def to_web_jpeg(image, longest_edge: int = 1800, quality: int = 80, path=None):
    """Export at Flickr-ish dimensions -- the Gate B stimulus.

    Lanczos down to ``longest_edge`` then JPEG at ``quality``. Both halves
    matter and they do not matter equally: on the R10 ladder, 1800px at
    quality 95 scores 408 while the same 1800px at quality 80 scores 37,
    which is the null. Resolution costs the fingerprint linearly; quantisation
    can take all of it at once.

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
        The image as re-read from the encoded JPEG, so the caller sees
        exactly the pixels a downloader would.
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


def green_channel(image):
    """The green channel of a delivered image, in [0, 1].

    Green rather than luminance: it is the channel with the most photosites
    behind it, and mixing channels dilutes the fingerprint with two weaker
    ones. Measured, luminance sits at the null where green scores 408.
    """
    return np.asarray(image, dtype=np.float32)[:, :, 1] / 255.0


def ladder(image, reference, steps=None):
    """Run the degradation ladder and return [(label, pce), ...].

    Parameters
    ----------
    image : PIL.Image.Image | str | Path
        A developed image, or a RAW path.
    reference : dict[int, np.ndarray] | np.ndarray
        An enrolled fingerprint. Per-plane fingerprints are collapsed with
        :func:`prnu.sensor_field`, since a resized image has no CFA lattice
        left to score plane by plane.
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
