/**
 * The correlation kernel, mirroring `fingerprint/prnu.py` and `cre/enclave.py`.
 *
 * BUILD.md sec.8 asks that this agree with the Python preprocessing
 * bit-for-bit. It does, by construction, for the part that matters: the
 * residual extraction is not here at all. The client extracts it before
 * anything leaves the machine, so there is exactly one implementation of the
 * wavelet stage and both backends call it.
 *
 * What IS reimplemented here is the correlation and the PCE, and those cannot
 * be bit-identical to numpy -- a radix-2 Cooley-Tukey and pocketfft accumulate
 * differently. `cre/validate_cre.py` measures the disagreement instead of
 * asserting it away.
 */

/** In-place iterative Cooley-Tukey. `n` must be a power of two. */
function fft1d(re: Float64Array, im: Float64Array, n: number, inverse: boolean): void {
	// Bit-reversal permutation.
	for (let i = 1, j = 0; i < n; i++) {
		let bit = n >> 1
		for (; j & bit; bit >>= 1) j ^= bit
		j ^= bit
		if (i < j) {
			;[re[i], re[j]] = [re[j], re[i]]
			;[im[i], im[j]] = [im[j], im[i]]
		}
	}

	for (let len = 2; len <= n; len <<= 1) {
		const angle = (2 * Math.PI) / len * (inverse ? 1 : -1)
		const wRe = Math.cos(angle)
		const wIm = Math.sin(angle)
		for (let i = 0; i < n; i += len) {
			let curRe = 1
			let curIm = 0
			for (let k = 0; k < len / 2; k++) {
				const uRe = re[i + k]
				const uIm = im[i + k]
				const vRe = re[i + k + len / 2] * curRe - im[i + k + len / 2] * curIm
				const vIm = re[i + k + len / 2] * curIm + im[i + k + len / 2] * curRe
				re[i + k] = uRe + vRe
				im[i + k] = uIm + vIm
				re[i + k + len / 2] = uRe - vRe
				im[i + k + len / 2] = uIm - vIm
				const nextRe = curRe * wRe - curIm * wIm
				curIm = curRe * wIm + curIm * wRe
				curRe = nextRe
			}
		}
	}

	if (inverse) {
		for (let i = 0; i < n; i++) {
			re[i] /= n
			im[i] /= n
		}
	}
}

/** 2-D transform of a square `size x size` array held row-major. */
function fft2d(re: Float64Array, im: Float64Array, size: number, inverse: boolean): void {
	const rowRe = new Float64Array(size)
	const rowIm = new Float64Array(size)

	for (let r = 0; r < size; r++) {
		const off = r * size
		for (let c = 0; c < size; c++) {
			rowRe[c] = re[off + c]
			rowIm[c] = im[off + c]
		}
		fft1d(rowRe, rowIm, size, inverse)
		for (let c = 0; c < size; c++) {
			re[off + c] = rowRe[c]
			im[off + c] = rowIm[c]
		}
	}

	for (let c = 0; c < size; c++) {
		for (let r = 0; r < size; r++) {
			rowRe[r] = re[r * size + c]
			rowIm[r] = im[r * size + c]
		}
		fft1d(rowRe, rowIm, size, inverse)
		for (let r = 0; r < size; r++) {
			re[r * size + c] = rowRe[r]
			im[r * size + c] = rowIm[r]
		}
	}
}

/** Subtract the mean, as `prnu._zero_mean_flat` does before every correlation. */
function zeroMean(a: Float64Array): Float64Array {
	let sum = 0
	for (let i = 0; i < a.length; i++) sum += a[i]
	const mean = sum / a.length
	const out = new Float64Array(a.length)
	for (let i = 0; i < a.length; i++) out[i] = a[i] - mean
	return out
}

/**
 * Circular cross-correlation surface of two zero-meaned fields, via FFT.
 * `prnu.cross_correlation`, term for term.
 */
export function crossCorrelation(a: Float64Array, b: Float64Array, size: number): Float64Array {
	const aRe = zeroMean(a)
	const aIm = new Float64Array(a.length)
	const bRe = zeroMean(b)
	const bIm = new Float64Array(b.length)

	fft2d(aRe, aIm, size, false)
	fft2d(bRe, bIm, size, false)

	// A * conj(B)
	const cRe = new Float64Array(a.length)
	const cIm = new Float64Array(a.length)
	for (let i = 0; i < a.length; i++) {
		cRe[i] = aRe[i] * bRe[i] + aIm[i] * bIm[i]
		cIm[i] = aIm[i] * bRe[i] - aRe[i] * bIm[i]
	}

	fft2d(cRe, cIm, size, true)
	return cRe // the real part, which is what `np.real` takes
}

/**
 * Peak-to-Correlation-Energy. `prnu._pce_of`.
 *
 * Signed on purpose: a strong *negative* peak is not a match, and taking the
 * absolute value would hide that. The 11x11 neighbourhood excluded around the
 * peak wraps, because the correlation surface is circular.
 */
export function pce(cc: Float64Array, size: number, squared = 11): number {
	let peakIndex = 0
	let best = -1
	for (let i = 0; i < cc.length; i++) {
		const v = Math.abs(cc[i])
		if (v > best) {
			best = v
			peakIndex = i
		}
	}
	const peak = cc[peakIndex]
	const peakRow = Math.floor(peakIndex / size)
	const peakCol = peakIndex % size

	const excluded = new Uint8Array(cc.length)
	const half = Math.floor(squared / 2)
	for (let dr = -half; dr <= half; dr++) {
		for (let dc = -half; dc <= half; dc++) {
			const r = (((peakRow + dr) % size) + size) % size
			const c = (((peakCol + dc) % size) + size) % size
			excluded[r * size + c] = 1
		}
	}

	let sum = 0
	let count = 0
	for (let i = 0; i < cc.length; i++) {
		if (!excluded[i]) {
			sum += cc[i] * cc[i]
			count++
		}
	}
	const energy = sum / count
	if (energy <= 0) return 0
	return Math.sign(peak) * ((peak * peak) / energy)
}

/** Root-mean-square of a surface, the per-plane normaliser in `prnu.score`. */
export function rms(a: Float64Array): number {
	let sum = 0
	for (let i = 0; i < a.length; i++) sum += a[i] * a[i]
	return Math.sqrt(sum / a.length)
}
