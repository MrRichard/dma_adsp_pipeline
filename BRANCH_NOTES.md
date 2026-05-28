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

## JC's original BASH script for reference
```bash
#!/bin/bash
# ------------------------------
# PET_preprocessing.sh
# ------------------------------
echo "Motion Correction - Tracer Check - Time Frame Selection - Time Averaging for PET Co-Registration..."

# Load necessary modules
module load fsl/6.0.7.4
module load ants/2.5.1
export FSLOUTPUTTYPE=NIFTI
echo "FSL output type: $FSLOUTPUTTYPE"

# Define Processing Directories
home="/isilon/datalake/dma_research/scratch/WisconsinADRC/Jeongchul"
freesurfer_dir="$home/Sample_code/sub-adrc00015-ses-07029"
output="$home/Sample_code/pet_output"
subj=$(basename $freesurfer_dir)
echo "Subject: $subj"

PET=$(find $home/Sample_code/$subj/pet -maxdepth 1 -type f -name "*.nii.gz")
json=$(find $home/Sample_code/$subj/pet -maxdepth 1 -type f -name "*.json")
echo "Found PET: $PET"
echo "Found JSON: $json"

# ------------------------------
# Step 1: Load JSON and check ScanStart and InjectionStart
# ------------------------------
tracer=$(grep -oP '"TracerName":\s*"\K[^"]+' $json)
scan_start=$(grep -oP '"ScanStart":\s*"\K[^"]+' $json)
injection_start=$(grep -oP '"InjectionStart":\s*"\K[^"]+' $json)
decay_corrected=$(grep -oP '"ImageDecayCorrected":\s*"\K[^"]+' $json)

echo "Tracer:          $tracer"
echo "Scan Start:      $scan_start"
echo "Injection Start: $injection_start"
echo "Decay Corrected: $decay_corrected"

# Check decay correction
if echo "$decay_corrected" | grep -q "DECY"; then
    echo "INFO: Image is decay corrected - no additional decay correction needed"
else
    echo "WARNING: Image may NOT be decay corrected - please check"
fi

# Calculate time difference between injection and scan start
injection_sec=$(echo $injection_start | awk -F: '{ print ($1 * 3600) + ($2 * 60) + $3 }')
scan_sec=$(echo $scan_start | awk -F: '{ print ($1 * 3600) + ($2 * 60) + $3 }')
diff_sec=$(( scan_sec - injection_sec ))
diff_min=$(echo "scale=2; $diff_sec / 60" | bc)

echo "-----------------------------------"
echo "Time from injection to scan start: ${diff_min} minutes"
echo "-----------------------------------"

mkdir -p $output

# ------------------------------
# Step 2: Motion Correction using ANTs (4D output)
# ------------------------------
echo "Motion Correction using ANTs for $subj..."

mc_prefix="$output/mc_PET_${subj}_"
mc_4d="$output/mc_PET_${subj}.nii"
mc_avg="$output/mc_PET_${subj}_avg.nii"

# Step 2a: Compute average of original 4D PET as reference
echo "Computing average of original 4D PET..."
antsMotionCorr \
    -d 3 \
    -a $PET \
    -o $mc_avg \
    -u 1 \
    -e 1 \
    -v 1

if [ ! -f "$mc_avg" ]; then
    echo "ERROR: ANTs averaging failed. Exiting."
    exit 1
fi

echo "=== Verifying average image ==="
fslstats $mc_avg -R -M

# Step 2b: Motion correction using average as reference
echo "Running motion correction using average as reference..."
antsMotionCorr \
    -d 3 \
    -o [ $mc_prefix, $mc_4d ] \
    -m MI[ $mc_avg, $PET, 1, 32, Regular, 0.2 ] \
    -t Rigid[ 0.1 ] \
    -i 25 \
    -e 1 \
    -s 0 \
    -f 1 \
    -u 1 \
    -v 1

if [ ! -f "$mc_4d" ]; then
    echo "ERROR: ANTs motion correction failed. Exiting."
    exit 1
fi
echo "ANTs motion correction done"

echo "=== Verifying motion corrected 4D ==="
fslstats $mc_4d -R -M

# ------------------------------
# Step 3: Split into frames and extract last 4
# ------------------------------
echo "Splitting motion-corrected PET into frames..."
fslsplit $mc_4d $output/vol -t

n_frames=$(fslnvols $mc_4d)
echo "Total frames: $n_frames"

start_idx=$(( n_frames - 4 ))
echo "Using frames $start_idx to $(( n_frames - 1 )) for time averaging"

last4_frames=""
for i in $(seq $start_idx $(( n_frames - 1 ))); do
    frame=$output/vol$(printf '%04d' $i).nii
    echo "  Including frame: $frame"
    last4_frames="$last4_frames $frame"
done

# ------------------------------
# Step 4: Merge last 4 frames and compute mean using ANTs
# ------------------------------
echo "Merging last 4 frames..."
fslmerge -t $output/last4_mc_PET_${subj}.nii $last4_frames

if [ ! -f "$output/last4_mc_PET_${subj}.nii" ]; then
    echo "ERROR: Merging last 4 frames failed. Exiting."
    exit 1
fi

echo "Computing time-averaged image from last 4 frames using ANTs..."
antsMotionCorr \
    -d 3 \
    -a $output/last4_mc_PET_${subj}.nii \
    -o $output/mean_mc_PET_${subj}.nii \
    -u 1 \
    -e 1 \
    -v 1

if [ ! -f "$output/mean_mc_PET_${subj}.nii" ]; then
    echo "ERROR: Time averaging failed. Exiting."
    exit 1
fi

# ------------------------------
# Step 5: Verify final output
# ------------------------------
echo "-----------------------------------"
echo "Verifying final averaged image..."
fslstats $output/mean_mc_PET_${subj}.nii -R -M
fslinfo $output/mean_mc_PET_${subj}.nii | grep -E "data_type|file_type|dim"
echo "-----------------------------------"
echo "Done."
echo "Motion corrected 4D : $mc_4d"
echo "Average reference   : $mc_avg"
echo "Time-averaged image  : $output/mean_mc_PET_${subj}.nii"
```
