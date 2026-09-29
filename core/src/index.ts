/**
 * Genesis verification, shared by the web page (`verify/`) and the desktop
 * app (`console-ui/`). See `docs/shared-verify-plan.md`.
 */

export { verify, stages, diagnose, MEASURED_AUC } from "./verify";
export type { VerifyResult, VerifyOptions, Verdict, Stage, Signal, LoadedBody, RawDecoder } from "./verify";
export { workerEngine, inProcessEngine } from "./engine";
export type { Engine } from "./engine";
export { createChainReader, nearest, MAX_HAMMING, CHAINS } from "./chain";
export type { ChainReader, ChainConfig, ChainKey, ImageRecord, BodyRecord } from "./chain";
export { cropKey, fractionOf, DETAIL_FLOOR } from "./analyse";
export type { Analysis, Candidate, ScoreResult, Signals, RawInput, OnStep } from "./analyse";
export { hashImage, isRaw, RAW_SUFFIXES } from "./hashes";
export type { Hashes } from "./hashes";
