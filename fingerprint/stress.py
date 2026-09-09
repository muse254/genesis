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


def strip_uniform_border(image, tolerance: float = 2.0, max_fraction: float = 0.25):
    """Remove a flat added margin, returning the photograph inside it.

    A border is neither a crop nor a resize and `crop_and_scale_search` models
    neither: it looks for a *uniform* scale, and padding changes the aspect
    ratio, so no single factor maps the canvas back onto the photosite
    lattice. Measured on a real file -- a 6000x4000 frame scores 90,846 and
    the same frame inside a 200px white margin, 6400x4400, scores 37.9 and
    reports "mirrored, 90 deg", which is the largest of eight orientations on
    noise. Cropped back to 6000x4000 it scores 86,097. The fingerprint was
    never damaged; the search could not find it.

    So this runs before the search rather than trying to make the search
    cleverer. Bordered exports are ordinary -- print margins, gallery frames,
    social templates -- and every one of them currently reads `no-record`,
    which is the wrong answer about a genuine photograph.

    Deliberately conservative. A row or column counts as border only if it is
    almost perfectly flat (`tolerance`, in 0-255 levels), and at most
    `max_fraction` of each side is ever removed, so a photograph that happens
    to open on sky or a studio backdrop cannot be eaten into. Nothing is
    removed unless all four sides agree there is a margin.

    Returns the image unchanged when there is no border to strip.
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

    # All four sides, or it is scene content rather than a frame. A photograph
    # with a blown sky has a flat top and nothing else.
    if min(top, bottom, left, right) == 0:
        return image

    box = (left, top, width - right, height - bottom)
    if box[2] - box[0] < width // 2 or box[3] - box[1] < height // 2:
        return image

    return image.crop(box)


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
