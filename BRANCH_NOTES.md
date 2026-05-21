# Feature Branch: `feature/jc_pet_changes`

## Purpose
Integrate Jeongchul's (JC) PET preprocessing workflow into the ADSP pipeline as an optional upgrade over the legacy approach.

## Summary of Changes

### 1. SUVR Fix (cherry-picked from `dev`)
- **File:** `job_generator.py`
- Added `grep -E '^[0-9]'` before `tail -n 1` in the cerebellum reference value extraction
- Prevents silent failure where trailing summary noise caused `$ref_val` to be empty

### 2. Config Layer (`config.py`)
- Added `pet_preprocessing` settings with default `method: "freesurfer_simple"` (legacy behavior)
- New option: `method: "ants_motion_correction"` enables JC's workflow

### 3. ANTs Preprocessing Method (`job_generator.py`)
New method: `_get_ants_preprocessing_script()`

When `pet_preprocessing.method = "ants_motion_correction"`:

1. **Pre-container (host-side, via SLURM module load):**
   - Loads `ants/2.5.1` and `fsl/6.0.7.4`
   - Computes reference average of raw 4D PET via `antsMotionCorr`
   - Runs rigid motion correction (Mutual Information metric)
   - Splits motion-corrected 4D into frames
   - Extracts last N frames (configurable, default: 4)
   - Averages them via `antsMotionCorr`
   - Cleans up intermediate files

2. **In-container changes:**
   - Skips `mri_concat --mean` (preprocessing already done)
   - Bind-mounts `$OUTPUT_DIR` instead of the raw BIDS PET directory
   - Copies `preproc_mean_{tracer}_{session_id}.nii.gz` instead of the raw 4D PET

### 4. Safety
- If frame count < `late_frame_count`, uses all available frames with a warning
- Each ANTs step checks output existence before continuing
- Intermediate files cleaned up after preprocessing

## Backward Compatibility
- Default `method: "freesurfer_simple"` preserves exact legacy behavior
- Only one config toggle needed to switch to JC's method

## Config Example
```yaml
pet_preprocessing:
  method: "ants_motion_correction"  # or "freesurfer_simple" (default)
  ants_module: "ants/2.5.1"
  fsl_module: "fsl/6.0.7.4"
  late_frame_count: 4
  use_json_metadata: true
```
