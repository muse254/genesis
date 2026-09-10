/**
 * Genesis confidential scoring — the algorithm is public, the reference is not.
 *
 * `scoring/app.py` is the trust hole by design: it holds K and you take its
 * word for a PCE. This is the fix. The correlation is published (it is in this
 * file, and the CRE beta reveals the binary anyway), K arrives from the Vault
 * DON inside an attested enclave, and only a score crosses back out.
 *
 * What this does NOT do is anything about forgery. An enclave would score a
 * planted fingerprint faithfully and sign it. Confidential compute protects the
 * reference from the verifier; the attack happens before the pixels arrive.
 * See `docs/security.md` — and do not let a demo of this imply otherwise.
 *
 * K arrives cropped and quantised because it has to: `WASMSecretsSizeLimit` is
 * 1mb and the reference is 89 MB. `docs/cre.md` measures what that costs.
 */

import { cre, hexToBase64, type TeeRuntime } from '@chainlink/cre-sdk'
import { encodeAbiParameters, parseAbiParameters, sha256 } from 'viem'
import { z } from 'zod'
import { crossCorrelation, pce, rms } from './correlate'

export const configSchema = z.object({
	/** Vault secret id per CFA plane, in plane order. */
	secretIds: z.array(z.string()),
	/** `prnu.PCE_THRESHOLD`, in thousandths so the enclave holds no floats. */
	thresholdMillis: z.number(),
})
type Config = z.infer<typeof configSchema>

const ATTESTATION_VERSION = 'genesis-cre-score-v1'
/** `prnu.SATURATION_LEVEL`. A clipped photosite is clamped, not modulated. */
const SATURATION_LEVEL = 0.99
const PLANES = [0, 1, 2, 3]

type Quantised = { scale: number; data: string }

const B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'

/** Hand-rolled so this does not depend on `atob` being present in the sandbox. */
function fromBase64(input: string): Uint8Array {
	const clean = input.replace(/=+$/, '')
	const out = new Uint8Array((clean.length * 3) >> 2)
	let bits = 0
	let acc = 0
	let n = 0
	for (let i = 0; i < clean.length; i++) {
		acc = (acc << 6) | B64.indexOf(clean[i])
		bits += 6
		if (bits >= 8) {
			bits -= 8
			out[n++] = (acc >> bits) & 0xff
		}
	}
	return out.subarray(0, n)
}

/** int8 back onto its own axis: the scale rides with the array. */
function restore(q: Quantised): Float64Array {
	const bytes = fromBase64(q.data)
	const out = new Float64Array(bytes.length)
	for (let i = 0; i < bytes.length; i++) {
		// int8 is signed; a Uint8Array is not.
		const signed = bytes[i] > 127 ? bytes[i] - 256 : bytes[i]
		out[i] = signed * q.scale
	}
	return out
}

function float64LE(value: number): Uint8Array {
	const buf = new ArrayBuffer(8)
	new DataView(buf).setFloat64(0, value, true)
	return new Uint8Array(buf)
}

/**
 * SHA-256 over the arrays in a fixed order, mirroring `payload.payload_digest`.
 *
 * Hashed field by field rather than over serialised JSON: a digest over a
 * pretty-printed object is a digest over whitespace. It binds the score to the
 * probe that produced it, so an attestation cannot be lifted onto other pixels.
 */
function payloadDigest(payload: any): `0x${string}` {
	const parts: Uint8Array[] = [
		new TextEncoder().encode(ATTESTATION_VERSION),
		new TextEncoder().encode(payload.bodyId),
		new Uint8Array([(payload.planeSize >> 8) & 0xff, payload.planeSize & 0xff]),
	]
	for (const c of PLANES) {
		const entry = payload.planes[String(c)]
		for (const field of ['residual', 'plane'] as const) {
			parts.push(float64LE(entry[field].scale))
			parts.push(fromBase64(entry[field].data))
		}
	}
	let total = 0
	for (const p of parts) total += p.length
	const flat = new Uint8Array(total)
	let at = 0
	for (const p of parts) {
		flat.set(p, at)
		at += p.length
	}
	return sha256(flat)
}

/**
 * Runs inside the enclave. `prnu.score`, with the residual already extracted
 * on the photographer's machine and K arriving from the Vault DON.
 */
export const onScoreRequest = (
	runtime: TeeRuntime<Config>,
	trigger: { input: Uint8Array },
): string => {
	const payload = JSON.parse(new TextDecoder().decode(trigger.input))
	const size = payload.planeSize
	const area = size * size

	let total: Float64Array | null = null

	for (const c of PLANES) {
		const id = runtime.config.secretIds[c]
		if (!id) continue

		// The Vault DON releases this only into an attested enclave, and it is
		// decrypted at the moment this call runs. One secret per CFA plane
		// because the CLI passes secret values as process arguments and ARG_MAX
		// is 1 MB — measured, not assumed.
		const k = restore(JSON.parse(runtime.getSecret({ id }).result().value) as Quantised)

		const entry = payload.planes[String(c)]
		const residual = restore(entry.residual)
		const plane = restore(entry.plane)

		// Drop saturated photosites from both sides: they carry no fingerprint
		// but still feed the energy the peak is measured against.
		const left = new Float64Array(area)
		const right = new Float64Array(area)
		for (let i = 0; i < area; i++) {
			const keep = plane[i] < SATURATION_LEVEL ? 1 : 0
			left[i] = residual[i] * keep
			right[i] = plane[i] * k[i] * keep
		}

		const cc = crossCorrelation(left, right, size)
		const norm = rms(cc)
		if (norm <= 0) continue

		// Normalise before summing so one plane cannot dominate on scale alone.
		if (total === null) {
			total = new Float64Array(area)
			for (let i = 0; i < area; i++) total[i] = cc[i] / norm
		} else {
			for (let i = 0; i < area; i++) total[i] += cc[i] / norm
		}
	}

	const score = total === null ? 0 : pce(total, size)
	const pceMillis = Math.round(score * 1000)
	const digest = payloadDigest(payload)

	// Cross back to the DON. Only the score and the digest of what was scored
	// go over; K, the residual and the plane stay inside. `usingTheDons()` is a
	// one-way door, so anything passed here is no longer confidential.
	const donRuntime = runtime.usingTheDons()
	donRuntime
		.report({
			encodedPayload: hexToBase64(
				encodeAbiParameters(parseAbiParameters('bytes32 digest, int256 pceMillis'), [
					digest,
					BigInt(pceMillis),
				]),
			),
			encoderName: 'evm',
			signingAlgo: 'ecdsa',
			hashingAlgo: 'keccak256',
		})
		.result()

	return JSON.stringify({
		version: ATTESTATION_VERSION,
		pceMillis,
		digest,
		thresholdMillis: runtime.config.thresholdMillis,
	})
}

export function initWorkflow(_config: Config) {
	const http = new cre.capabilities.HTTPCapability()
	return [
		cre.handlerInTee(http.trigger({}), onScoreRequest, [
			{ tee: 'nitro', regions: ['us-west-2'] },
		]),
	]
}
