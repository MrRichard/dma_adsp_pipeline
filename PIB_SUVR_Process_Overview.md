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
- **Goal**: Generate a comprehensive set of mosaic images to visually inspect the quality and outputs of the processing pipeline.
- **Process**:
    1.  **Environment Activation**: A dedicated Python virtual environment (specified by `python_venv_path` in the configuration) is activated to ensure access to necessary libraries (`nilearn`, `matplotlib`, etc.).
    2.  **GM Mask Creation**: A gray matter (GM) mask is generated from the subject's FreeSurfer `aparc+aseg` segmentation. This is used for one of the QC overlays.
    3.  **Mosaic Generation**: The `create_qc_mosaics.py` script is executed three times to produce the following PNG images, each showing axial, coronal, and off-center sagittal views:
        - **Registration QC**: The PET image co-registered to the T1w MRI (`pib_pet_space-T1w.nii.gz`) is overlaid on the T1w image to verify alignment accuracy.
        - **Segmentation QC**: The generated Gray Matter (GM) mask is overlaid on the T1w image to verify the tissue segmentation.
        - **SUVR Map QC**: The final SUVR map (`pib_SUVR.nii.gz`) is overlaid on the T1w image to visualize the final output.
