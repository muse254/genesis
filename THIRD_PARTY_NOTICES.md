# Third-party notices

Genesis is MIT licensed (`LICENSE`). Two pieces of other people's code are
built into it under their own licenses.

## LibRaw 0.22.1

`core/raw/build.sh` compiles LibRaw to WASM for decoding RAW files in the
browser. LibRaw is copyright LibRaw LLC, and is dual-licensed under
the GNU Lesser General Public License 2.1 and the Common Development and
Distribution License 1.0. Genesis uses it under the **LGPL 2.1**.

- The source is not vendored. The build script fetches the unmodified release
  from <https://www.libraw.org/data/LibRaw-0.22.1.tar.gz>, checks it against a
  pinned SHA-256, and builds it.
- Genesis does not modify LibRaw.
- The WASM links LibRaw with `core/raw/decode.cpp`. Everything needed to
  rebuild that module against a modified LibRaw is in this repository:
  `decode.cpp`, `data_helper.h` and `build.sh`. That is what LGPL 2.1
  section 6 asks for.
- License texts: <https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html>,
  and `LICENSE.LGPL` / `LICENSE.CDDL` inside the LibRaw tarball.

Anyone redistributing the built `.wasm` must ship this notice with it, and
must point to LibRaw's source or include it.

## rawpy `data_helper.h`

`core/raw/data_helper.h` is vendored unchanged from rawpy 0.27.1. It is
copyright (c) 2014 Maik Riechert, MIT licensed, and the full notice is kept at
the top of the file.
