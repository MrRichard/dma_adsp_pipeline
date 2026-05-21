# Branch: `feature/jc_pet_changes`

**Created:** May 21, 2026
**Branched from:** `dev` (23dc35b — SUVR grep fix committed)

## Purpose
Integrate Jeongchul's (JC) PET preprocessing improvements into the PiB/tracer pipeline, and fix the silent SUVR reference value collection bug.

## Files Changed

### `mr_pet_pipeline/mr_pet_pipeline/job_generator.py`
- **Line 724** (SUVR fix): Added `grep -E '^[0-9]'` to `mri_segstats` pipeline to avoid silent fallback on trailing noise lines
- **Lines 409-526** (`_get_ants_preprocessing_script`): Host-side ANTs rigid motion correction + late-frame averaging. Follows JC's workflow: compute reference avg → motion correct → split → extract last N frames → average
- **Lines ~800-830** (`_generate_pet_slurm_content`): Conditional logic — skips in-container `mri_concat --mean` when ANTs preprocessing is active, swaps bind-mount source and input filename
- **Lines ~940-975** (JSON metadata + provenance): Parses PET sidecar `.json` for `TracerName`, `ScanStart`, `InjectionStart`, `ImageDecayCorrected` using `python3 -c ...` (with grep fallback). Calculates injection-to-scan delay. Writes all to `provenance.txt`. Gated by `pet_preprocessing.use_json_metadata`.

### `mr_pet_pipeline/mr_pet_pipeline/config.py`
- **Lines 64-71**: `pet_preprocessing` section with `method`, `ants_module`, `fsl_module`, `late_frame_count`, `use_json_metadata`

### `mr_pet_pipeline/config/example_config.yaml`
- **Lines 29-38**: Documented `pet_preprocessing` options with comments explaining both methods

## New Files
- **`BRANCH_NOTES.md`**: This file — tracks scope and decisions

## Config Options

```yaml
pet_preprocessing:
  method: "freesurfer_simple"          # or "ants_motion_correction"
  ants_module: "ants/2.5.1"            # HPC module for motion correction
  fsl_module: "fsl/6.0.7.4"            # HPC module for frame splitting
  late_frame_count: 4                  # frames to average (PiB protocol)
  use_json_metadata: true              # parse sidecar for scan/injection timing
```

## Safety
- Falls back to averaging all frames if total < `late_frame_count`
- Checks ANTs output before proceeding
- ANTs preprocessing runs **on the HPC host** (module load) — FreeSurfer stays in its Singularity container
- Existing `freesurfer_simple` method entirely unchanged for backward compatibility
