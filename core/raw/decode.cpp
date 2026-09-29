/*
 * RAW sensor data with LibRaw, compiled to WASM by build.sh, for enrolling
 * a camera in the browser (docs/shared-verify-plan.md; the Python side is
 * fingerprint/prnu.py::load_raw_planes and cfa_pattern).
 *
 * Returns exactly the fields enrolment reads through `rawpy`, computed the
 * way `rawpy` 0.27.1 computes them, from the same LibRaw version (0.22.1):
 *
 *   raw_image_visible        the undeveloped mosaic, margins removed
 *   raw_pattern              COLOR() over an n x n tile, reduced 4 -> 2
 *   raw_colors_visible       that tile wrapped over the full raw, then cut
 *   black_level_per_channel  rawpy's adjust_bl_ (vendored, data_helper.h)
 *   white_level              imgdata.rawdata.color.maximum
 *
 * No demosaicing and no processing: enrolment splits the mosaic into its
 * CFA planes itself. The sensor values are lossless-decoded data, so any
 * correct decoder agrees on them; the metadata rules above are where a
 * port could silently differ, which is why they are copied, not re-derived.
 *
 * One file at a time: raw_open() replaces the previous one.
 */
#include <cstdlib>
#include <cstring>

#include <emscripten/emscripten.h>

#include "libraw/libraw.h"
#include "data_helper.h"

static LibRaw *raw;
static char message[256];
static unsigned short *visible;
static int pattern_n;
static unsigned char pattern[16][16];
static libraw_colordata_black_level_t black;

extern "C" {

EMSCRIPTEN_KEEPALIVE void raw_close(void) {
  free(visible);
  visible = nullptr;
  pattern_n = 0;
  if (raw) {
    raw->recycle();
    delete raw;
    raw = nullptr;
  }
}

/* rawpy's raw_pattern: COLOR() relative to the visible area, over an n x n
 * tile whose size depends on the filter layout, and a 4 x 4 tile that is
 * really 2 x 2 reduced to 2 x 2. 0 on success. */
static int compute_pattern(void) {
  unsigned filters = raw->imgdata.idata.filters;
  int n;
  if (filters < 1000) {
    if (filters == 0) n = 1;                   // black and white
    else if (filters == 1) n = 16;             // Leaf Catchlight
    else if (filters == LIBRAW_XTRANS) n = 6;
    else return -1;
  } else {
    n = 4;
  }
  int top = raw->imgdata.sizes.top_margin, left = raw->imgdata.sizes.left_margin;
  for (int y = 0; y < n; y++)
    for (int x = 0; x < n; x++) pattern[y][x] = (unsigned char)raw->COLOR(y - top, x - left);
  if (n == 4) {
    bool twice = true;
    for (int y = 0; y < 2; y++)
      for (int x = 0; x < 2; x++)
        twice = twice && pattern[y][x] == pattern[y][x + 2] && pattern[y][x] == pattern[y + 2][x + 2] &&
                pattern[y][x] == pattern[y + 2][x];
    if (twice) n = 2;
  }
  pattern_n = n;
  return 0;
}

/* Open and unpack a RAW file held in memory. 0 on success; on failure,
 * raw_error() says why. */
EMSCRIPTEN_KEEPALIVE int raw_open(const unsigned char *data, size_t size) {
  raw_close();
  message[0] = 0;
  raw = new LibRaw();
  int e = raw->open_buffer(data, size);
  if (e == LIBRAW_SUCCESS) e = raw->unpack();
  if (e != LIBRAW_SUCCESS) {
    strncpy(message, libraw_strerror(e), sizeof(message) - 1);
    raw_close();
    return 1;
  }
  if (raw->imgdata.rawdata.raw_image == nullptr) {
    // rawpy's RawType.Stack: already demosaiced (a linear DNG), no mosaic.
    strcpy(message, "not a CFA mosaic (a linear or demosaiced raw)");
    raw_close();
    return 2;
  }
  if (compute_pattern() != 0) {
    strcpy(message, "unsupported CFA filter layout");
    raw_close();
    return 3;
  }
  black = adjust_bl_(raw);

  const libraw_image_sizes_t &s = raw->imgdata.sizes;
  visible = (unsigned short *)malloc((size_t)s.width * s.height * sizeof(unsigned short));
  if (!visible) {
    strcpy(message, "out of memory");
    raw_close();
    return 4;
  }
  for (int y = 0; y < s.height; y++)
    memcpy(visible + (size_t)y * s.width,
           raw->imgdata.rawdata.raw_image + (size_t)(y + s.top_margin) * s.raw_width + s.left_margin,
           (size_t)s.width * sizeof(unsigned short));
  return 0;
}

EMSCRIPTEN_KEEPALIVE const char *raw_error(void) { return message; }

/* raw_image_visible, row-major, width x height uint16. */
EMSCRIPTEN_KEEPALIVE const unsigned short *raw_visible(void) { return visible; }
EMSCRIPTEN_KEEPALIVE int raw_width(void) { return raw ? raw->imgdata.sizes.width : 0; }
EMSCRIPTEN_KEEPALIVE int raw_height(void) { return raw ? raw->imgdata.sizes.height : 0; }

/* raw_pattern: n x n. */
EMSCRIPTEN_KEEPALIVE int raw_pattern_size(void) { return pattern_n; }
EMSCRIPTEN_KEEPALIVE int raw_pattern_at(int y, int x) { return pattern[y][x]; }

/* raw_colors_visible at (y, x): the pattern wrapped over the full raw (numpy
 * pad mode='wrap' from the raw's origin), then cut to the visible area. */
EMSCRIPTEN_KEEPALIVE int raw_color_visible(int y, int x) {
  const libraw_image_sizes_t &s = raw->imgdata.sizes;
  return pattern[(y + s.top_margin) % pattern_n][(x + s.left_margin) % pattern_n];
}

/* black_level_per_channel[c], c in 0..3. */
EMSCRIPTEN_KEEPALIVE unsigned raw_black(int c) { return black.cblack[c]; }
/* white_level. */
EMSCRIPTEN_KEEPALIVE unsigned raw_white(void) { return raw ? raw->imgdata.rawdata.color.maximum : 0; }

/* Identity, for refusing a set of frames from more than one camera. */
EMSCRIPTEN_KEEPALIVE const char *raw_make(void) { return raw ? raw->imgdata.idata.make : ""; }
EMSCRIPTEN_KEEPALIVE const char *raw_model(void) { return raw ? raw->imgdata.idata.model : ""; }
EMSCRIPTEN_KEEPALIVE const char *raw_body_serial(void) { return raw ? raw->imgdata.shootinginfo.BodySerial : ""; }

EMSCRIPTEN_KEEPALIVE const char *raw_libraw_version(void) { return LibRaw::version(); }
}
