# Verification evidence — narration-driven rendering milestone

## Sample artifact

- Job: `b55babc8f8ea414f` (live providers)
- Output: `data/jobs/b55babc8f8ea414f/output.mp4`
- State: `READY_FOR_APPROVAL`
- Provider mode: `live` for all LLM stages; real Edge TTS for narration.

`ffprobe` reported H.264, yuv420p, BT.709 limited range, 1080×1920, 30 FPS and 1098 video frames. AAC audio is 48 kHz stereo. Container duration is 36.608 seconds; file size is 2,852,953 bytes.

The physical audio scan measured -16.01 LUFS integrated loudness and -5.10 dBTP true peak. Configured black-gap, long-silence and frozen-scene detectors reported no events. All sixteen technical checks in `qc.json` passed; editorial and factual flags remain false.

Four scene frames were inspected in `evidence/contact-sheet.png`. Their titles and bottom captions were readable without clipping or overlap, and the `DEMO / MOCK SCRIPT` label was present. No independent listening or ASR alignment result is claimed.

## Executed checks

| Check | Actual result |
| --- | --- |
| Python suite | `48 passed in 3.05s` |
| Ruff | `All checks passed!` |
| Exported JSON Schemas | `12 artifact schemas verified` |
| Credential pattern scan | `0 findings` |
| Python dependency compatibility | `All installed packages are compatible` |
| Video TypeScript | `tsc --noEmit`, exit 0 |
| npm production dependency audit | `found 0 vulnerabilities` |
| KineticTypography standalone still | Rendered, exit 0 |
| EducationalExplainer standalone still | Rendered, exit 0 |
| Completed-job resume | All nine production stages reused validated artifacts; exit 0 |

The credential scanner checks version-control candidates using known patterns; it is not a complete security audit. npm audit covered production dependencies. The default Python tests isolate runtime storage and do not call live models or network TTS.

No new paid live model run was performed for this milestone. Exact Opus 5.5 identity, a complete strict live-only production run, source verification, scheduling/reboot reliability and publishing remain unverified/unimplemented as detailed in `IMPLEMENTATION_STATUS.md`.
