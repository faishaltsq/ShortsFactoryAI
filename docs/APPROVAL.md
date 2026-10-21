# Editorial eligibility and operator approval

## Boundaries

The production pipeline stops at `READY_FOR_APPROVAL`. It never approves a job or invokes the publishing service. The dashboard/API and Hermes integration remain observation-only. Local operator commands approve or reject a job.

`editorial_qc.json` and `approval.json` contain deterministic checks over the artifacts. A model-generated draft review remains a separate artifact (`draft_qc.json`). Neither the deterministic gate nor quote matching is an independent semantic fact checker.

## Required evidence

Eligibility requires valid canonical contracts for the script, storyboard, source verification, originality, draft review, technical QC, metadata, assets, audio, and render. Missing or malformed artifacts are blockers, not passing defaults.

The gate checks:

- Technical QC passes, every recorded technical check passes, and its checksum identifies the current render.
- Draft editorial review passes and its input fingerprint matches the current script and storyboard.
- Metadata has a nonempty title and description and identifies the current script.
- Physical narration and MP4 exist inside the job directory. Checksums, dependency hashes, measured durations and FFprobe properties validate through the media validators.
- Live factual scripts have replayable quote checks against stored, checksum-identified source text. The evidence identifies the current script. An unread source or `needs_review` status cannot pass the live factual gate.
- Fictional content is explicitly labelled `fictional`; it does not receive factual clearance.
- Live originality is enforced against the current script text. Fixture runs record overlap without rejecting identical fixtures.

Mock factual content may reach local review with `needs_review`. This does not authorize publishing mock content. Publishing separately refuses fixture provenance.

## Commands

```bash
# Generate or resume a local demo through the operator boundary.
# Default content providers are fixtures; audio still uses network-backed Edge TTS.
uv run python scripts/run_pipeline.py --title "Demo untuk ditinjau" --stop approval
uv run python scripts/run_pipeline.py --resume JOB_ID --stop approval

# Inspect pending jobs; no approval occurs.
uv run python scripts/approve.py --list

# Explicit operator decisions.
uv run python scripts/approve.py --approve JOB_ID --by operator
uv run python scripts/approve.py --reject JOB_ID --reason "Judul perlu diperbaiki" --by operator
```

`--live` uses configured live providers; it is not required to test the local fixture workflow. The `--stop editorial` command stops after deterministic editorial QC rather than creating approval eligibility.

## Cache invalidation and stale decisions

Draft review and metadata receipts identify their inputs. Resume reuses a current receipt without another provider call. A changed storyboard invalidates the draft review; a changed script invalidates both draft review and metadata. Invalid canonical artifacts fail validation instead of being silently accepted.

Editorial eligibility is recomputed on resume, not trusted from a cached boolean. Operator approval rereads physical media and requires both gate artifacts to identify the current input fingerprint. A changed title, script, evidence, media, or other bound input invalidates a stale approval verdict. Rerun the editorial gate before approving edited inputs.

The operator decision records `approved_by`, `approved_at`, and `approved_inputs_sha256` in the job payload. A production runner does not modify an already approved/uploaded/scheduled job; those states belong to the separate operator/publishing workflow.

## Verification boundary

`tests/test_approval.py` uses labelled offline test audio and a real FFmpeg-generated MP4. These tests exercise missing/corrupt media, dependency hashes, gate rejection, stale inputs, replayable quotes, and explicit decisions. Test audio is not a live TTS result and is not production music. `tests/test_pipeline_mock.py` exercises provider-cache invalidation without contacting model services.

Live YouTube account authorization, uploads, and public publication remain separate actions requiring operator permission.
