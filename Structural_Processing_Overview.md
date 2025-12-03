# Structural MRI Processing Pipeline Overview

This document outlines the key steps of the structural MRI processing pipeline, which is orchestrated by the `_generate_freesurfer_slurm_content` method in the `job_generator.py` script. The entire process is executed within a Singularity container to ensure a reproducible FreeSurfer 8.0 environment.

---

## Step 1: Main FreeSurfer Reconstruction (`recon-all`)

The core of the structural pipeline is the execution of FreeSurfer's `recon-all` command.

- **Goal**: Perform a full cortical reconstruction from the subject's T1-weighted (T1w) image.
- **Inputs**:
    - The primary T1w anatomical image.
    - An optional FLAIR image, which can be used to improve pial surface estimation (`-FLAIR` flag).
- **Process**:
    1.  A temporary directory is created to stage input files.
    2.  The T1w and (if available) FLAIR images are copied into this temporary directory.
    3.  A script named `run_freesurfer.sh` is generated within this directory.
    4.  The Singularity container is launched, mounting the necessary input, output, and license directories.
    5.  Inside the container, `run_freesurfer.sh` executes the `recon-all` command with the `-all` directive to run all reconstruction steps.
- **Output**: A standard FreeSurfer subject directory containing `mri`, `surf`, `stats`, `label`, and other subdirectories with the full reconstruction results.

---

## Step 2: Advanced Segmentation Modules (Optional)

If `run_additional_modules` is set to `true` in the configuration file, several advanced segmentation tools are run sequentially after `recon-all` completes. These steps are executed within the same FreeSurfer container job.

### 2a. White Matter Hyperintensity Segmentation
- **Goal**: Segment white matter hyperintensities (WMH).
- **Tool**: `mri_WMHsynthseg`.
- **Output**:
    - A segmentation volume: `mri/wmh_synthseg.mgz`.
    - A CSV file with volume measurements: `mri/wmh_volumes.csv`.

### 2b. Hypothalamic Subunit Segmentation
- **Goal**: Perform detailed segmentation of hypothalamic subunits.
- **Tool**: `mri_segment_hypothalamic_subunits`.
- **Output**: Volumetric segmentations of the hypothalamic subunits (e.g., `mri/hypothalamic_subunits_lh.v1.mgz`).

### 2c. Hippocampal and Amygdala Segmentation
- **Goal**: Segment hippocampal subfields and nuclei of the amygdala.
- **Tool**: `segment_subregions hippo-amygdala`.
- **Output**: Detailed segmentation volumes for the left and right hemispheres (e.g., `mri/lh.hippoAmygLabels-T1.v21.mgz`).

---

## Step 3: Brainnetome Atlas Application (Optional)

If `run_brainnetome` is set to `true` in the configuration, the Brainnetome Atlas is applied to the subject's reconstructed brain surface. This provides a parcellation with 246 cortical regions.

- **Goal**: Apply the Brainnetome atlas for enhanced regional analysis.
- **Tools**: `mris_ca_label`, `mri_aparc2aseg`, `mri_segstats`.
- **Process**:
    1.  **Surface Labeling**: `mris_ca_label` is used to map the Brainnetome atlas (`.gcs` files) onto the subject's spherical surface registration for both the left (`lh`) and right (`rh`) hemispheres.
    2.  **Volumetric Conversion**: `mri_aparc2aseg` converts the resulting surface annotation (`.annot` files) into a single volumetric segmentation file.
    3.  **Statistical Analysis**: `mri_segstats` is run to generate statistics (e.g., volume, thickness) for each of the 246 Brainnetome regions.
- **Output**:
    - Surface annotations: `label/lh.BN_Atlas.annot` and `label/rh.BN_Atlas.annot`.
    - A volumetric atlas file: `mri/BN_Atlas+aseg.mgz`.
    - Regional statistics files: `stats/lh.BN_Atlas.stats` and `stats/rh.BN_Atlas.stats`.
