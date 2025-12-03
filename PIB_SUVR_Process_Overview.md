# PIB PET Processing Pipeline Overview

This document outlines the key steps of the PiB PET processing pipeline as implemented in the `pet_processing_script.sh`.

The process is executed within a Singularity container environment, leveraging tools from FreeSurfer and other neuroimaging packages.

### Step 1: Initialization and Setup
- **Environment**: A Singularity container is used to provide a consistent environment with all necessary software (FreeSurfer, FSL, etc.).
- **Inputs**: The pipeline requires three main inputs:
    1. The raw PiB PET image (`trc-11CPiB.nii.gz`).
    2. The corresponding FreeSurfer segmentation directory for the subject.
    3. A designated output directory.

### Step 2: PET to T1w Registration
- **Goal**: Align the PET image with the subject's T1-weighted (T1w) structural MRI.
- **Tool**: `mri_coreg` from FreeSurfer.
- **Process**:
    1. The mean PET image is registered to the `norm.mgz` volume from the subject's FreeSurfer output.
    2. A 6-degrees-of-freedom transformation is calculated and saved to a registration file (`pib_pet_to_T1w.lta`).
- **Output**: A resampled PET volume in T1w space (`pib_pet_space-T1w.nii.gz`).

### Step 3: SUVR Normalization
- **Goal**: Normalize the PET signal to a reference region to create a Standardized Uptake Value Ratio (SUVR) map.
- **Reference Region**:
    - For **Tau PET**, the script is designed to use the brainstem as the reference region.
    - For **PiB PET**, the current script **does not use a reference region**. It simply uses the raw, co-registered PET values from the previous step. The resulting file is named `pib_SUVR.nii.gz` for consistency, but it does not represent a true ratio-based SUVR.

### Step 4: Partial Volume Correction (PVC)
- **Goal**: Correct for the partial volume effect, where the signal from adjacent tissues (like gray matter and white matter) can blur together due to the limited resolution of PET scanners.
- **Tool**: `petpvc`.
- **Method**: The script uses the Müller-Gärtner (`MG`) method.
- **Process**:
    1. The FreeSurfer segmentation (`aparc+aseg.mgz`) is converted to NIfTI format.
    2. `petpvc` is run on the `pib_SUVR.nii.gz` image using the segmentation to create a corrected version.
- **Output**: A PVC-corrected image (`pib_SUVR_pvc.nii.gz`).

### Step 5: Regional Statistics Extraction
- **Goal**: Quantify the PET signal in various anatomical regions of interest (ROIs).
- **Tool**: `mri_segstats` from FreeSurfer.
- **Process**:
    1. `mri_segstats` is run on the **non-corrected** `pib_SUVR.nii.gz` image using the DKT atlas from the `aparc+aseg` segmentation.
    2. The results (mean, standard deviation, volume, etc. for each region) are saved to `pib_DKT_stats.txt` and then formatted into `pib_DKT_stats.csv`.
    3. This process is **repeated** for the **PVC-corrected** `pib_SUVR_pvc.nii.gz` image, generating `pib_DKT_stats_pvc.csv`.

### Step 6: Quality Control (QC)
- **Goal**: Generate images to visually inspect the quality of the processing.
- **Process**:
    1. A NIfTI file of the PET image overlaid on the T1w MRI is created (`qc/pib_pet_on_T1w.nii.gz`).
    2. A Python script (`qc_pet_overlay.py`) is called to generate a PNG image showing this overlay from axial, sagittal, and coronal perspectives.
