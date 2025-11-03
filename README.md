# MR-PET Processing Pipeline

A comprehensive neuroimaging pipeline for automated processing of BIDS-formatted MR and PET data using FreeSurfer and SLURM job scheduling.

**Developed by:** Radiology Informatics and Information Processing Laboratory  
**Institution:** Wake Forest University School of Medicine - Department of Radiology

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Usage](#usage)
- [Processing Modes](#processing-modes)
- [Output Structure](#output-structure)
- [Advanced Features](#advanced-features)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## Overview

The MR-PET Processing Pipeline automates the processing of structural MRI (T1w, FLAIR) and PET imaging data (Tau, PIB) following BIDS conventions. It orchestrates FreeSurfer reconstruction, optional advanced segmentation modules, and PET-to-MR registration with ROI quantification.

### Key Capabilities

- **BIDS-compliant** dataset parsing for MR and PET sessions
- **Automated session matching** between MR and PET based on age proximity
- **FreeSurfer 8.0** reconstruction with optional enhancements
- **Multi-tracer PET support** (Tau, PIB, extensible to others)
- **Intelligent processing** - skips already completed sessions
- **SLURM job generation** with automatic dependency management
- **Flexible modes** - structural-only or combined MR-PET processing

---

## Features

### Structural MR Processing
- FreeSurfer `recon-all` with T1w ± FLAIR
- Optional advanced modules:
  - WMH-SynthSeg (white matter hyperintensities)
  - Hypothalamic subunit segmentation
  - Hippocampal subfields and amygdala nuclei
- Brainnetome atlas parcellation (246 cortical regions)

### PET Processing
- Automated PET-to-T1w registration using FreeSurfer tools (`mri_coreg`)
- SUVR calculation with cerebellar reference (Tau)
- ROI-based quantification using FreeSurfer parcellations
- Quality control image generation

### Smart Processing
- **Incremental processing** - automatically skips completed sessions
- **Force reprocessing** option to override existing outputs
- **Structural-only mode** for MR-only datasets
- **Multi-tracer support** with independent PET directories

---

## Requirements

### System Requirements
- Linux HPC environment with SLURM scheduler
- Singularity/Apptainer for containerized FreeSurfer
- Python 3.8+

### Software Dependencies
- FreeSurfer 8.0 container (`.sif` file)
- FreeSurfer license file
- Brainnetome atlas files (optional)

### Python Packages
```
pyyaml >= 6.0
pandas >= 1.5.0
```

---

## Installation

### 1. Clone the Repository
```bash
git clone <repository-url>
cd mr_pet_pipeline
```

### 2. Install the Package
```bash
# Development install
pip install -e .

# Or regular install
pip install .
```

### 3. Verify Installation
```bash
python -c "import mr_pet_pipeline; print(mr_pet_pipeline.__version__)"
```

---

## Quick Start

### 1. Prepare Your Configuration

Copy and edit the example configuration:
```bash
cp mr_pet_pipeline/config/example_config.yaml my_config.yaml
```

### 2. Validate Configuration
```bash
python scripts/run_pipeline.py --config my_config.yaml --validate-only
```

### 3. Run the Pipeline
```bash
# Generate job files
python scripts/run_pipeline.py --config my_config.yaml

# Submit jobs to SLURM
./output_directory/submit_all_jobs.sh
```

---

## Configuration

### Minimal Configuration (Structural Only)

```yaml
# Required paths
bids_dir: "/path/to/bids/data/"
output_dir: "/path/to/output/"
container_path: "/path/to/freesurfer8.0_enhanced.sif"
freesurfer_license: "~/freesurfer_license.txt"

# Processing mode
structural_only: true
force_reprocess: false

# Optional enhancements
brainnetome_dir: "/path/to/BN_Atlas_freesurfer/"
run_additional_modules: true
run_brainnetome: true

# SLURM settings
slurm:
  partition: "defq"
  account: "your-account"
```

### Full Configuration (MR-PET)

```yaml
# Required paths
bids_dir: "/path/to/bids/data/"
output_dir: "/path/to/output/"
container_path: "/path/to/freesurfer8.0_enhanced.sif"
freesurfer_license: "~/freesurfer_license.txt"

# PET directories by tracer
pet_dirs:
  tau: "/path/to/tau_pet/"
  pib: "/path/to/pib_pet/"

# Processing settings
structural_only: false
tracers: ["tau", "pib"]
max_age_difference: 5.0  # years
force_reprocess: false

# Optional enhancements
brainnetome_dir: "/path/to/BN_Atlas_freesurfer/"
run_additional_modules: true
run_brainnetome: true
run_pvc: false

# SLURM settings
slurm:
  partition: "defq"
  account: "your-account"
  freesurfer:
    time: "24:00:00"
    memory: "64G"
    cpus: 8
    gpus: 1
  pet:
    time: "4:00:00"
    memory: "16G"
    cpus: 4
```

### Key Configuration Options

| Option | Description | Default |
|--------|-------------|---------|
| `structural_only` | Process only MR data (skip PET) | `false` |
| `force_reprocess` | Reprocess existing completed sessions | `false` |
| `max_age_difference` | Max age difference for MR-PET matching (years) | `5.0` |
| `tracers` | List of PET tracers to process | `["tau", "pib"]` |
| `run_additional_modules` | Enable WMH, hypothalamus, hippocampus modules | `true` |
| `run_brainnetome` | Add Brainnetome atlas parcellation | `true` |
| `require_flair` | Only process sessions with FLAIR | `false` |

---

## Usage

### Basic Usage

```bash
# Standard run
python scripts/run_pipeline.py --config config.yaml

# Dry run (setup without submitting)
python scripts/run_pipeline.py --config config.yaml --dry-run

# Verbose output
python scripts/run_pipeline.py --config config.yaml --verbose

# Validate only
python scripts/run_pipeline.py --config config.yaml --validate-only
```

### Workflow

1. **Pipeline Setup** - The script will:
   - Parse BIDS directory for MR sessions
   - Find and match PET sessions (if not structural-only)
   - Check for existing completed FreeSurfer recons
   - Generate SLURM job scripts with dependencies
   - Create submission script and summary reports

2. **Job Submission** - Run the generated script:
   ```bash
   cd /path/to/output
   ./submit_all_jobs.sh
   ```

3. **Monitor Progress**:
   ```bash
   # Check job queue
   squeue -u $USER
   
   # Check logs
   tail -f output_directory/jobs/*_output.txt
   ```

---

## Processing Modes

### 1. Structural-Only Mode

Process only MR data without PET matching.

**When to use:**
- MR-only datasets
- Initial structural processing before PET data arrives
- Testing FreeSurfer pipeline

**Configuration:**
```yaml
structural_only: true
```

**Behavior:**
- Processes all available MR sessions
- No PET directory required
- Only generates FreeSurfer jobs
- Skips session matching

### 2. MR-PET Mode

Full pipeline with MR-PET session matching.

**When to use:**
- Datasets with both MR and PET
- Multi-tracer studies

**Configuration:**
```yaml
structural_only: false
pet_dirs:
  tau: "/path/to/tau/"
  pib: "/path/to/pib/"
tracers: ["tau", "pib"]
```

**Behavior:**
- Matches MR and PET sessions by age
- Generates FreeSurfer jobs
- Generates PET processing jobs with dependencies
- Supports multiple tracers per session

### 3. Incremental Processing

Add new subjects without reprocessing existing data.

**Configuration:**
```yaml
force_reprocess: false  # Default
```

**Behavior:**
- Skips sessions with completed recons
- Only processes new or incomplete sessions
- Reports skipped sessions in summary

### 4. Force Reprocessing

Reprocess all sessions, including completed ones.

**Configuration:**
```yaml
force_reprocess: true
```

**Behavior:**
- Removes existing FreeSurfer output directories
- Reprocesses all matched sessions
- Use with caution - will overwrite existing results

---

## Output Structure

```
output_directory/
├── freesurfer/
│   ├── sub-001_ses-07691/
│   │   ├── mri/
│   │   ├── surf/
│   │   ├── label/
│   │   ├── stats/
│   └── sub-002_ses-08234/
│       └── ...
├── pet/
│   ├── sub-001_ses-07691/
│   │   ├── tau/
│   │   │   ├── tau_SUVR.nii.gz
│   │   │   ├── tau_DKT_stats.csv
│   │   │   └── qc/
│   │   └── pib/
│   │       └── ...
│   └── ...
├── jobs/
│   ├── sub-001_ses-07691_freesurfer.slurm
│   ├── sub-001_ses-07691_tau_pet.slurm
│   ├── sub-001_ses-07691_pib_pet.slurm
│   ├── *_output.txt
│   └── *_error.txt
├── logs/
│   └── pipeline_*.log
├── submit_all_jobs.sh
├── pipeline_summary.json
└── pipeline_summary.txt
```

### Key Output Files

#### FreeSurfer Outputs
- `mri/`: Volumetric outputs (norm.mgz, aparc+aseg.mgz, BN_Atlas+aseg.mgz)
- `surf/`: Surface reconstructions
- `stats/`: Regional statistics files
- `label/`: Parcellation labels (including Brainnetome)

#### PET Outputs
- `{tracer}_SUVR.nii.gz`: Standardized uptake value ratio image
- `{tracer}_DKT_stats.csv`: ROI-based quantification
- `qc/`: Quality control images

#### Pipeline Outputs
- `submit_all_jobs.sh`: Master job submission script
- `pipeline_summary.json`: Detailed processing summary
- `pipeline_summary.txt`: Human-readable summary

---

## Advanced Features

### Brainnetome Atlas

Enhanced 246-region cortical parcellation.

**Requirements:**
- `lh.BN_Atlas.gcs` and `rh.BN_Atlas.gcs` files

**Outputs:**
- `label/lh.BN_Atlas.annot` and `rh.BN_Atlas.annot`
- `mri/BN_Atlas+aseg.mgz`
- `stats/lh.BN_Atlas.stats` and `rh.BN_Atlas.stats`

### Additional Segmentation Modules

**WMH-SynthSeg:**
- White matter hyperintensity segmentation
- Output: `mri/wmh_synthseg.mgz`, `mri/wmh_volumes.csv`

**Hypothalamic Subunits:**
- Detailed hypothalamus parcellation
- Output: `mri/hypothalamic_subunits_*.mgz`

**Hippocampal Subfields:**
- Hippocampus and amygdala subregion segmentation
- Output: `mri/[lr]h.hippoAmygLabels-T1*.mgz`

### Session Matching Algorithm

When `structural_only: false`, the pipeline matches MR and PET sessions:

1. Groups sessions by subject ID
2. Calculates age difference between all MR-PET pairs
3. Filters pairs with age difference > `max_age_difference`
4. Assigns optimal 1:1 matches (greedy algorithm, sorted by age difference)
5. Supports multiple tracers per MR session

---

## Troubleshooting

### Common Issues

**1. "FreeSurfer output directory already exists"**

*Cause:* FreeSurfer requires output directory to not exist before running.

*Solution:*
- Set `force_reprocess: true` to automatically remove and reprocess
- Or manually remove: `rm -rf output_dir/freesurfer/sub-XXX_ses-YYY`

**2. "No PET sessions found"**

*Cause:* PET files not properly organized or named.

*Solution:*
- Verify BIDS structure: `pet_dir/sub-XXX/ses-YYY/pet/*.nii.gz`
- Check PET filename contains tracer identifier (`tau`, `mk6240`, or `pib`)
- Verify `pet_dirs` paths in config are correct

**3. "Configuration validation failed"**

*Cause:* Missing required files or directories.

*Solution:*
- Run with `--validate-only` to see specific errors
- Check all paths in config file exist
- Verify FreeSurfer license file is readable

**4. Jobs fail immediately after submission**

*Cause:* SLURM configuration or container issues.

*Solution:*
- Check job error logs: `output_dir/jobs/*_error.txt`
- Verify SLURM account and partition names
- Test container manually: `singularity exec container.sif ls`

**5. "All sessions have completed FreeSurfer recons"**

*Cause:* All sessions were previously processed.

*Solution:*
- This is normal for incremental processing
- Use `force_reprocess: true` if you need to reprocess
- Add new subjects to BIDS directory for incremental processing

### Getting Help

Check the detailed logs:
```bash
# Pipeline orchestration log
cat output_dir/logs/pipeline_*.log

# Individual job logs
cat output_dir/jobs/sub-*_output.txt
cat output_dir/jobs/sub-*_error.txt
```

---

## BIDS Directory Structure

Expected input structure:

```
bids_dir/
├── sub-001/
│   ├── ses-07691/
│   │   └── anat/
│   │       ├── sub-001_ses-07691_T1w.nii.gz
│   │       └── sub-001_ses-07691_FLAIR.nii.gz (optional)
│   └── ses-08234/
│       └── ...
└── sub-002/
    └── ...

pet_dir/
├── sub-001/
│   ├── ses-07691/
│   │   └── pet/
│   │       └── sub-001_ses-07691_tau.nii.gz
│   └── ses-08234/
│       └── ...
└── sub-002/
    └── ...
```

**Session naming convention:**
- Session format: `ses-XXXXX` where XXXXX represents age
- Example: `ses-07691` = age 76.91 years
- Age extracted automatically for MR-PET matching

---

## Performance Considerations

### Resource Requirements

**FreeSurfer recon-all:**
- Time: ~8-24 hours per subject (depending on options)
- Memory: 64GB recommended
- CPUs: 8 cores recommended
- GPU: Optional (1 GPU for faster processing)

**PET processing:**
- Time: ~1-4 hours per tracer
- Memory: 16GB
- CPUs: 4 cores

### Optimization Tips

1. **Parallel Processing:** Submit jobs in batches
2. **GPU Acceleration:** Use GPUs for FreeSurfer when available
3. **Incremental Updates:** Use `force_reprocess: false` for new subjects only
4. **Storage:** Ensure sufficient space (~5GB per subject for FreeSurfer)

---

## Development Notes

### Extending the Pipeline

**Adding new PET tracers:**

1. Add tracer directory to config:
   ```yaml
   pet_dirs:
     amyloid: "/path/to/amyloid/"
   tracers: ["tau", "pib", "amyloid"]
   ```

2. Update tracer classification in `parsers.py`:
   ```python
   def _classify_pet_tracer(self, pet_file: Path) -> Optional[str]:
       filename_lower = pet_file.name.lower()
       if 'amyloid' in filename_lower:
           return 'amyloid'
       # ... existing logic
   ```

### Testing

```bash
# Test with dry-run
python scripts/run_pipeline.py --config test_config.yaml --dry-run --verbose

# Test with small dataset
python scripts/run_pipeline.py --config test_config.yaml --validate-only
```

---

## Citation

If you use this pipeline in your research, please cite:

```
Radiology Informatics and Information Processing Laboratory
Wake Forest University School of Medicine
Department of Radiology
```

---

## License

[Specify License Here]

---

## Contact

**Radiology Informatics and Information Processing Laboratory (RIIPL)**  
Wake Forest University School of Medicine  
Department of Radiology

For questions or support, please contact [contact information].

---

## Version History

### Version 1.0.0
- Initial release
- FreeSurfer 8.0 integration
- Multi-tracer PET support
- Structural-only processing mode
- Incremental processing with existing recon detection
- Brainnetome atlas integration
- Advanced segmentation modules (WMH, hypothalamus, hippocampus)

---

## Acknowledgments

This pipeline integrates and automates several established neuroimaging tools:
- FreeSurfer (Fischl et al.)
- Brainnetome Atlas (Fan et al.)
- WMH-SynthSeg
- Hippocampal Subfields and Nuclei of Amygdala segmentation