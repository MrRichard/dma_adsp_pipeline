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
