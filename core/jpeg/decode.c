/*
 * JPEG -> RGB8 with libjpeg-turbo (WASM, build.sh). The pixel hash is exact,
 * so this must match Pillow byte for byte: same library, same version,
 * libjpeg defaults. CMYK/YCCK is refused: Pillow converts those with its own
 * formula, and a wrong hash would read as "no record", not an error.
 * One image at a time: decode() replaces the previous result.
 */
#include <setjmp.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <emscripten/emscripten.h>

#include "jpeglib.h"
#include "jerror.h"

static unsigned char *result;
static int result_width, result_height;
static char message[JMSG_LENGTH_MAX + 64];

struct error_mgr {
  struct jpeg_error_mgr pub;
  jmp_buf jump;
};

static void on_error(j_common_ptr cinfo) {
  struct error_mgr *err = (struct error_mgr *)cinfo->err;
  (*cinfo->err->format_message)(cinfo, message);
  longjmp(err->jump, 1);
}

/* Warnings are ignored, as in Pillow, except truncation: Pillow refuses it,
 * while libjpeg would pad with grey and give a silently wrong hash. */
static void on_warning(j_common_ptr cinfo, int level) {
  if (level < 0 && cinfo->err->msg_code == JWRN_JPEG_EOF) {
    strcpy(message, "the file is truncated");
    longjmp(((struct error_mgr *)cinfo->err)->jump, 1);
  }
}

EMSCRIPTEN_KEEPALIVE void release(void) {
  free(result);
  result = NULL;
  result_width = result_height = 0;
}

/* Returns 0 on success; on failure, error_message() says why. */
EMSCRIPTEN_KEEPALIVE int decode(const unsigned char *data, unsigned long size) {
  struct jpeg_decompress_struct cinfo;
  struct error_mgr err;
  unsigned char *volatile out = NULL;

  release();
  message[0] = 0;

  cinfo.err = jpeg_std_error(&err.pub);
  err.pub.error_exit = on_error;
  err.pub.emit_message = on_warning;
  if (setjmp(err.jump)) {
    jpeg_destroy_decompress(&cinfo);
    free(out);
    return 1;
  }

  jpeg_create_decompress(&cinfo);
  jpeg_mem_src(&cinfo, data, size);
  jpeg_read_header(&cinfo, TRUE);

  if (cinfo.jpeg_color_space == JCS_CMYK || cinfo.jpeg_color_space == JCS_YCCK) {
    strcpy(message, "CMYK JPEGs are not supported");
    jpeg_destroy_decompress(&cinfo);
    return 1;
  }
  cinfo.out_color_space = JCS_RGB;

  jpeg_start_decompress(&cinfo);
  size_t stride = (size_t)cinfo.output_width * 3;
  out = malloc(stride * cinfo.output_height);
  if (!out) {
    strcpy(message, "out of memory decoding the JPEG");
    jpeg_destroy_decompress(&cinfo);
    return 1;
  }
  while (cinfo.output_scanline < cinfo.output_height) {
    JSAMPROW row = out + stride * cinfo.output_scanline;
    jpeg_read_scanlines(&cinfo, &row, 1);
  }
  jpeg_finish_decompress(&cinfo);

  result = out;
  result_width = cinfo.output_width;
  result_height = cinfo.output_height;
  jpeg_destroy_decompress(&cinfo);
  return 0;
}

EMSCRIPTEN_KEEPALIVE unsigned char *result_pixels(void) { return result; }
EMSCRIPTEN_KEEPALIVE int result_w(void) { return result_width; }
EMSCRIPTEN_KEEPALIVE int result_h(void) { return result_height; }
EMSCRIPTEN_KEEPALIVE const char *error_message(void) { return message; }
