"""Degradation ladder: how much insult does the fingerprint survive?

Applies each transform a published image actually undergoes -- resize, JPEG
re-encode at descending quality, crop, mild sharpening, a social-platform
round trip -- and records the PCE after each.

This produces the evidence behind the retroactive claim. Gate B (BUILD.md
sec.9) is one row of this table promoted to a go/no-go decision.
"""


def ladder(image, reference, steps=None):
    """Run the degradation ladder and return [(label, pce), ...]."""
    raise NotImplementedError


def to_web_jpeg(image, longest_edge: int = 1800, quality: int = 80):
    """Export at Flickr-ish dimensions -- the Gate B stimulus."""
    raise NotImplementedError
