"""
SLURM job generation for FreeSurfer and PET processing
"""
import logging
from pathlib import Path
from typing import List
from datetime import datetime

from .data_models import SubjectSession
from .config import PipelineConfig


class SLURMJobGenerator:
    """Generate SLURM job scripts for the pipeline"""
    
    def __init__(self, config: PipelineConfig):
        self.config = config
        self.logger = logging.getLogger(__name__)
        
    def create_freesurfer_job(self, session: SubjectSession) -> Path:
        """
        Create SLURM job for FreeSurfer processing with Brainnetome
        
        Args:
            session: SubjectSession object
            
        Returns:
            Path to created job file
        """
        job_dir = self.config.output_dir / "jobs"
        job_dir.mkdir(parents=True, exist_ok=True)
        
        session_id = session.get_session_id()
        job_file = job_dir / f"{session_id}_freesurfer.slurm"
        
        # FreeSurfer will create this directory - we must NOT create it beforehand
        fs_subjects_dir = self.config.output_dir / "freesurfer"
        fs_output_dir = fs_subjects_dir / session_id
        
        job_content = self._generate_freesurfer_slurm_content(session, session_id, fs_subjects_dir, fs_output_dir)
        
        job_file.write_text(job_content)
        job_file.chmod(0o755)
        
        self.logger.debug(f"Created FreeSurfer job: {job_file}")
        return job_file
    
    def create_pet_processing_job(self, session: SubjectSession) -> List[Path]:
        """
        Create SLURM jobs for PET processing
        
        Args:
            session: SubjectSession object with PET files
            
        Returns:
            List of paths to created job files
        """
        job_files = []
        
        for tracer, pet_file in session.pet_files.items():
            job_dir = self.config.output_dir / "jobs"
            session_id = session.get_session_id()
            job_file = job_dir / f"{session_id}_{tracer}_pet.slurm"
            
            job_content = self._generate_pet_slurm_content(session, tracer, session_id)
            
            job_file.write_text(job_content)
            job_file.chmod(0o755)
            
            job_files.append(job_file)
            self.logger.debug(f"Created PET job: {job_file}")
        
        return job_files
    
    def _generate_freesurfer_slurm_content(self, session, session_id, fs_subjects_dir, fs_output_dir):
        """Generate SLURM script content for FreeSurfer processing"""
        
        flair_option = ""
        flair_copy = ""
        if session.flair_file:
            flair_option = f"-FLAIR /input_data/{session.flair_file.name}"
            flair_copy = f'cp {session.flair_file} $input_dir/'
        
        # Additional modules based on config
        additional_modules = self._get_additional_modules_script(session_id)
        
        # Brainnetome atlas addition
        brainnetome_section = self._get_brainnetome_script(session_id)
        
        # Handle force reprocessing
        force_reprocess_check = ""
        if self.config.force_reprocess:
            force_reprocess_check = f"""
# Force reprocessing - remove existing output if present
if [ -d "{fs_output_dir}" ]; then
    echo "WARNING: Removing existing FreeSurfer output (force_reprocess=true)"
    rm -rf {fs_output_dir}
fi
"""
        else:
            force_reprocess_check = f"""
# Check for existing FreeSurfer output (directory should not exist before recon-all)
if [ -d "{fs_output_dir}" ]; then
    echo "ERROR: FreeSurfer output directory already exists: {fs_output_dir}"
    echo "FreeSurfer requires this directory to NOT exist before running."
    echo "To reprocess this subject, either:"
    echo "  1. Set force_reprocess: true in config, or"
    echo "  2. Manually remove: {fs_output_dir}"
    echo "Exiting without processing."
    exit 1
fi
"""
        
        fs_config = self.config.slurm.freesurfer
        
        return f"""#!/bin/bash
#SBATCH --job-name=FS_{session_id[:12]}
#SBATCH --output={self.config.output_dir}/jobs/{session_id}_fs_output.txt
#SBATCH --error={self.config.output_dir}/jobs/{session_id}_fs_error.txt
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus={fs_config.get('gpus', 1)}
#SBATCH --cpus-per-task={fs_config['cpus']}
#SBATCH --mem={fs_config['memory']}
#SBATCH --time={fs_config['time']}
#SBATCH --account={self.config.slurm.account}
#SBATCH --partition={self.config.slurm.partition}

# Load required modules
module load singularity

# Set environment variables
export FS_LICENSE={self.config.freesurfer_license}
export FREESURFER_HOME="/usr/local/freesurfer/8.0.0-1"

echo "Starting FreeSurfer processing for {session_id}"
echo "T1w: {session.t1w_file}"
{f'echo "FLAIR: {session.flair_file}"' if session.flair_file else 'echo "No FLAIR image"'}
echo "Output: {fs_output_dir}"
echo "Started at: $(date)"

{force_reprocess_check}

# Create parent output directory (but NOT the subject directory - let FreeSurfer create it)
mkdir -p {fs_output_dir.parent}

# Copy input files to a temporary location
input_dir={self.config.output_dir}/temp_input_{session_id}
mkdir -p $input_dir
cp {session.t1w_file} $input_dir/
{flair_copy}

# Create processing script in temporary directory (NOT in FreeSurfer output)
cat << 'EOF' > $input_dir/run_freesurfer.sh
#!/bin/bash

# Source FreeSurfer environment
. /usr/local/freesurfer/8.0.0-1/SetUpFreeSurfer.sh

echo "=== Starting recon-all ==="
echo "Subject: {session_id}"
echo "Starting at: $(date)"

# Run FreeSurfer recon-all
recon-all \\
  -i /input_data/{session.t1w_file.name} \\
  {flair_option} \\
  -subjid {session_id} \\
  -all \\
  -sd /output/

# Check if recon-all completed successfully
if [ $? -ne 0 ]; then
    echo "ERROR: recon-all failed for {session_id}"
    exit 1
fi

echo "=== recon-all completed at: $(date) ==="
{additional_modules}
{brainnetome_section}

echo "=== FreeSurfer processing completed at: $(date) ==="
EOF

chmod +x $input_dir/run_freesurfer.sh

# Run FreeSurfer in singularity container
singularity exec --nv \\
  --env FREESURFER_HOME="/usr/local/freesurfer/8.0.0-1" \\
  --env SUBJECTS_DIR="/output/" \\
  -B {self.config.freesurfer_license}:/usr/local/freesurfer/8.0.0-1/license.txt \\
  -B $input_dir:/input_data/ \\
  -B {fs_output_dir.parent}:/output/ \\
  -B {self.config.brainnetome_dir}:/brainnetome_files/ \\
  -B /scratch:/scratch \\
  {self.config.container_path} \\
  bash /input_data/run_freesurfer.sh

# Check completion status
if [ $? -eq 0 ]; then
    echo "SUCCESS: FreeSurfer processing completed for {session_id}"
    touch {fs_output_dir}/freesurfer_completed.flag
else
    echo "ERROR: FreeSurfer processing failed for {session_id}"
    exit 1
fi

# Cleanup temp input
rm -rf $input_dir

echo "FreeSurfer processing completed at: $(date)"
"""

    def _get_additional_modules_script(self, session_id: str) -> str:
        """Get script section for additional FreeSurfer modules"""
        if not self.config.run_additional_modules:
            return ""
        
        fs_config = self.config.slurm.freesurfer
        
        return f"""
echo "=== Running additional segmentation modules ==="

# WMH-SynthSeg (White Matter Hyperintensities)
echo "Running WMH-SynthSeg..."
mri_WMHsynthseg \\
  --i /output/{session_id}/mri/norm.mgz \\
  --o /output/{session_id}/mri/wmh_synthseg.mgz \\
  --csv_vols /output/{session_id}/mri/wmh_volumes.csv \\
  --threads {fs_config['cpus']} --crop

# Hypothalamic Subunits
echo "Running Hypothalamic Subunits..."
mri_segment_hypothalamic_subunits \\
  --s {session_id} \\
  --sd /output/ \\
  --threads {fs_config['cpus']} \\
  --cpu

# Hippocampal Subfields and Nuclei of Amygdala
echo "Running Hippocampal Subfields and Nuclei of Amygdala..."
export SUBJECTS_DIR=/output/
segment_subregions hippo-amygdala --cross {session_id}
"""

    def _get_brainnetome_script(self, session_id: str) -> str:
        """Get script section for Brainnetome atlas"""
        if not self.config.run_brainnetome:
            return ""
        
        return f"""
echo "=== Adding Brainnetome Atlas ==="

# Create label directory if needed
mkdir -p /output/{session_id}/label

# Add Brainnetome atlas - left hemisphere
echo "Processing left hemisphere Brainnetome atlas..."
mris_ca_label -orig white -novar \\
    {session_id} lh sphere.reg \\
    /brainnetome_files/lh.BN_Atlas.gcs \\
    /output/{session_id}/label/lh.BN_Atlas.annot

# Add Brainnetome atlas - right hemisphere  
echo "Processing right hemisphere Brainnetome atlas..."
mris_ca_label -orig white -novar \\
    {session_id} rh sphere.reg \\
    /brainnetome_files/rh.BN_Atlas.gcs \\
    /output/{session_id}/label/rh.BN_Atlas.annot

# Generate Brainnetome aparc2aseg (volumetric version)
echo "Generating volumetric Brainnetome atlas..."
mri_aparc2aseg --s {session_id} --annot BN_Atlas \\
    --o /output/{session_id}/mri/BN_Atlas+aseg.mgz

# Generate statistics
echo "Generating Brainnetome atlas statistics..."
mri_segstats --annot {session_id} lh BN_Atlas \\
    --sum /output/{session_id}/stats/lh.BN_Atlas.stats

mri_segstats --annot {session_id} rh BN_Atlas \\
    --sum /output/{session_id}/stats/rh.BN_Atlas.stats
"""

    def _get_pvc_processing_script(self, session_id: str, tracer: str) -> str:
        """Generate PVC processing preparation section"""
        if not self.config.run_pvc:
            return ""
        
        # Get PVC parameters from config
        pvc_method = getattr(self.config, 'pvc_method', 'MG')
        pvc_fwhm = getattr(self.config, 'pvc_fwhm', [6.0, 6.0, 6.0])
        fwhm_str = f"{pvc_fwhm[0]},{pvc_fwhm[1]},{pvc_fwhm[2]}"
        
        return f"""
echo "=== Preparing for Partial Volume Correction ==="

# Convert FreeSurfer segmentation to NIfTI for PETPVC
mri_convert /fs_subjects/{session_id}/mri/aparc+aseg.mgz \\
    aparc+aseg.nii.gz

if [ $? -ne 0 ]; then
    echo "ERROR: Failed to convert segmentation"
    exit 1
fi

echo "Segmentation converted successfully"

# Create PVC working directory
mkdir -p pvc_work
cd pvc_work
cp ../{tracer}_SUVR.nii.gz .
cp ../aparc+aseg.nii.gz .
cd ..

echo "PVC setup complete (Method: {pvc_method}, FWHM: {fwhm_str} mm)"
"""

    def _generate_pet_slurm_content(self, session: SubjectSession, 
                                   tracer: str, session_id: str) -> str:
        """Generate SLURM script content for PET processing with optional PVC using separate container"""
        
        pet_settings = self.config.slurm.pet
        pvc_section = self._get_pvc_processing_script(session_id, tracer)
        
        # PVC parameters
        pvc_method = getattr(self.config, 'pvc_method', 'MG')
        pvc_fwhm = getattr(self.config, 'pvc_fwhm', [6.0, 6.0, 6.0])
        fwhm_str = f"{pvc_fwhm[0]},{pvc_fwhm[1]},{pvc_fwhm[2]}"
        
        # Determine if we should run PVC
        run_pvc = self.config.run_pvc
        petpvc_container = getattr(self.config, 'petpvc_container', None)
        
        # PVC execution block (runs in host, using separate PETPVC container)
        # NOTE: Using raw string to avoid escape sequence warnings
        pvc_execution = ""
        if run_pvc and petpvc_container:
            # Build the bash script separately to avoid escape issues
            pvc_stats_script = r"""
    cd /output
    
    # Generate statistics for DKT atlas regions (PVC-corrected)
    mri_segstats --i """ + f"{tracer}_SUVR_pvc.nii.gz" + r""" \
                 --seg /fs_subjects/""" + f"{session_id}" + r"""/mri/aparc+aseg.mgz \
                 --ctab /usr/local/freesurfer/8.0.0-1/FreeSurferColorLUT.txt \
                 --sum """ + f"{tracer}_DKT_ROI_stats_pvc.txt" + r"""
    
    # Create simple CSV format for PVC data
    echo 'Region,Mean_SUVR_PVC,Volume_mm3' > """ + f"{tracer}_DKT_stats_pvc.csv" + r"""
    tail -n +3 """ + f"{tracer}_DKT_ROI_stats_pvc.txt" + r""" | while read line; do
        if [[ $line =~ ^[[:space:]]*[0-9] ]]; then
            region=$(echo $line | awk '{print $5}')
            volume=$(echo $line | awk '{print $4}')
            mean_val=$(echo $line | awk '{print $6}')
            echo "$region,$mean_val,$volume" >> """ + f"{tracer}_DKT_stats_pvc.csv" + r"""
        fi
    done
    
    echo 'PVC statistics extraction completed'
"""
            
            pvc_execution = f"""
echo ""
echo "=== Running PETPVC Container for Partial Volume Correction ==="

# Run PETPVC in separate container
singularity exec \\
  -B $OUTPUT_DIR:/data \\
  -B $FS_DIR:/fs_data \\
  {petpvc_container} \\
  petpvc \\
    -i /data/pvc_work/{tracer}_SUVR.nii.gz \\
    -m /data/pvc_work/aparc+aseg.nii.gz \\
    -o /data/{tracer}_SUVR_pvc.nii.gz \\
    --pvc {pvc_method} \\
    --fwhm {fwhm_str}

if [ $? -ne 0 ]; then
    echo "ERROR: PETPVC failed"
    exit 1
fi

echo "PVC completed successfully"

# Extract ROI statistics from PVC-corrected image
echo "Extracting ROI statistics from PVC-corrected image..."

singularity exec --nv \\
  --env FREESURFER_HOME="/usr/local/freesurfer/8.0.0-1" \\
  --env SUBJECTS_DIR="/fs_subjects/" \\
  -B {self.config.freesurfer_license}:/usr/local/freesurfer/8.0.0-1/license.txt \\
  -B $FS_DIR:/fs_subjects/{session_id} \\
  -B $OUTPUT_DIR:/output/ \\
  {self.config.container_path} \\
  bash -c "{pvc_stats_script}"

if [ $? -eq 0 ]; then
    echo "SUCCESS: PVC statistics extracted"
else
    echo "ERROR: Failed to extract PVC statistics"
    exit 1
fi

# Cleanup PVC working directory
rm -rf $OUTPUT_DIR/pvc_work

echo "PVC processing completed at: $(date)"
"""
        
        return f"""#!/bin/bash
#SBATCH --job-name=PET_{tracer}_{session_id[:10]}
#SBATCH --output={self.config.output_dir}/jobs/{session_id}_{tracer}_output.txt
#SBATCH --error={self.config.output_dir}/jobs/{session_id}_{tracer}_error.txt
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task={pet_settings['cpus']}
#SBATCH --mem={pet_settings['memory']}
#SBATCH --time={pet_settings['time']}
#SBATCH --account={self.config.slurm.account}
#SBATCH --partition={self.config.slurm.partition}
#SBATCH --dependency=afterok:${{FREESURFER_JOB_ID}}

# Load required modules
module load singularity

# Set environment variables
export FS_LICENSE={self.config.freesurfer_license}

echo "Starting {tracer.upper()} PET processing for {session_id}"
echo "Started at: $(date)"
{"echo 'PVC: ENABLED (" + pvc_method + " method, FWHM=" + fwhm_str + ")'" if run_pvc else "echo 'PVC: DISABLED'"}

# Define paths
PET_FILE={session.pet_files[tracer]}
FS_DIR={self.config.output_dir}/freesurfer/{session_id}
OUTPUT_DIR={self.config.output_dir}/pet/{session_id}/{tracer}

# Check if PET output already exists
if [ -f "$OUTPUT_DIR/pet_processing_completed.flag" ]; then
    echo "WARNING: PET processing output already exists for {session_id} {tracer}"
    if [ "{self.config.force_reprocess}" = "True" ]; then
        echo "Force reprocessing enabled - removing existing output"
        rm -rf "$OUTPUT_DIR"
    else
        echo "Skipping (set force_reprocess: true to reprocess)"
        exit 0
    fi
fi

mkdir -p $OUTPUT_DIR/qc
cd $OUTPUT_DIR

# Create PET processing script to run in FreeSurfer container
cat << 'EOF' > pet_processing_script.sh
#!/bin/bash

# Source FreeSurfer environment
. /usr/local/freesurfer/8.0.0-1/SetUpFreeSurfer.sh

echo "=== Starting PET processing ==="
echo "Tracer: {tracer}"
echo "Starting at: $(date)"

# Copy PET file
cp /pet_input/$(basename {session.pet_files[tracer]}) mean_{tracer}_on_MR.nii.gz

# Decompress if needed
if [[ mean_{tracer}_on_MR.nii.gz == *.gz ]]; then
    gunzip mean_{tracer}_on_MR.nii.gz
fi

echo "=== PET-to-MR Registration ==="

# Step 1: Register PET to FreeSurfer T1w using mri_coreg
echo "Running mri_coreg for PET-to-T1w registration..."
mri_coreg \\
  --mov mean_{tracer}_on_MR.nii \\
  --ref /fs_subjects/{session_id}/mri/norm.mgz \\
  --reg {tracer}_pet_to_T1w.lta \\
  --dof 6 \\
  --threads {pet_settings['cpus']} \\
  --no-coord-dither

if [ $? -ne 0 ]; then
    echo "ERROR: mri_coreg failed"
    exit 1
fi

echo "Registration completed successfully"

# Step 2: Apply registration to create coregistered PET in T1w space
echo "Applying registration with mri_vol2vol..."
mri_vol2vol \\
  --mov mean_{tracer}_on_MR.nii \\
  --targ /fs_subjects/{session_id}/mri/norm.mgz \\
  --reg {tracer}_pet_to_T1w.lta \\
  --o {tracer}_pet_space-T1w.nii.gz \\
  --no-save-reg

if [ $? -ne 0 ]; then
    echo "ERROR: mri_vol2vol failed"
    exit 1
fi

echo "Coregistered PET created successfully"

# Step 3: Create QC overlay images
echo "Creating QC images..."
mkdir -p qc

# Generate QC overlay (PET on T1w for visual inspection)
mri_vol2vol \\
  --mov mean_{tracer}_on_MR.nii \\
  --targ /fs_subjects/{session_id}/mri/T1.mgz \\
  --reg {tracer}_pet_to_T1w.lta \\
  --o qc/{tracer}_pet_on_T1w.nii.gz \\
  --no-save-reg

echo "QC images created"

# Step 4: Basic SUVR calculation (if this is tau, use cerebellar reference)
if [ "{tracer}" = "tau" ]; then
    echo "=== Calculating tau SUVR ==="
    
    # Extract cerebellar gray matter from FreeSurfer aparc+aseg
    # Using brainstem as reference region for tau
    mri_binarize --i /fs_subjects/{session_id}/mri/aparc+aseg.mgz \\
                 --match 16 --o cerebellum_ref.mgz
    
    # Convert to same space as coregistered PET
    mri_vol2vol --mov cerebellum_ref.mgz \\
                --targ {tracer}_pet_space-T1w.nii.gz \\
                --regheader \\
                --o cerebellum_ref_pet_space.nii.gz \\
                --nearest
    
    # Calculate mean in reference region
    ref_val=$(mri_segstats --i {tracer}_pet_space-T1w.nii.gz \\
                          --seg cerebellum_ref_pet_space.nii.gz \\
                          --id 1 --avgwf | tail -1 | awk '{{print $6}}')
    
    echo "Reference region value: $ref_val"
    
    # Calculate SUVR
    if [ $(echo "$ref_val > 0" | bc -l) -eq 1 ]; then
        mri_calc -o {tracer}_SUVR.nii.gz {tracer}_pet_space-T1w.nii.gz div $ref_val
        echo "SUVR calculation completed"
    else
        echo "WARNING: Invalid reference value, using raw PET values"
        cp {tracer}_pet_space-T1w.nii.gz {tracer}_SUVR.nii.gz
    fi
else
    echo "Using raw PET values for {tracer}"
    cp {tracer}_pet_space-T1w.nii.gz {tracer}_SUVR.nii.gz
fi
{pvc_section}
# Step 5: Extract basic ROI statistics using FreeSurfer tools
echo "=== Extracting ROI statistics (Raw) ==="

# Generate statistics for DKT atlas regions
mri_segstats --i {tracer}_SUVR.nii.gz \\
             --seg /fs_subjects/{session_id}/mri/aparc+aseg.mgz \\
             --ctab /usr/local/freesurfer/8.0.0-1/FreeSurferColorLUT.txt \\
             --sum {tracer}_DKT_ROI_stats.txt

# Create simple CSV format
echo "Region,Mean_SUVR,Volume_mm3" > {tracer}_DKT_stats.csv
tail -n +3 {tracer}_DKT_ROI_stats.txt | while read line; do
    if [[ $line =~ ^[[:space:]]*[0-9] ]]; then
        region=$(echo $line | awk '{{print $5}}')
        volume=$(echo $line | awk '{{print $4}}')
        mean_val=$(echo $line | awk '{{print $6}}')
        echo "$region,$mean_val,$volume" >> {tracer}_DKT_stats.csv
    fi
done

echo "=== PET processing (in-container) completed at: $(date) ==="
EOF

chmod +x pet_processing_script.sh

# Run PET processing in FreeSurfer container
echo "Running PET processing in FreeSurfer container..."
singularity exec --nv \\
  --env FREESURFER_HOME="/usr/local/freesurfer/8.0.0-1" \\
  --env SUBJECTS_DIR="/fs_subjects/" \\
  -B {self.config.freesurfer_license}:/usr/local/freesurfer/8.0.0-1/license.txt \\
  -B $(dirname {session.pet_files[tracer]}):/pet_input/ \\
  -B $FS_DIR:/fs_subjects/{session_id} \\
  -B $OUTPUT_DIR:/output/ \\
  -B /scratch:/scratch \\
  {self.config.container_path} \\
  bash /output/pet_processing_script.sh

# Check completion of FreeSurfer container processing
if [ $? -ne 0 ]; then
    echo "ERROR: PET processing in FreeSurfer container failed"
    exit 1
fi

echo "FreeSurfer container processing completed successfully"
{pvc_execution}
# Final completion check
if [ $? -eq 0 ]; then
    echo "SUCCESS: {tracer.upper()} PET processing completed for {session_id}"
    touch pet_processing_completed.flag
else
    echo "ERROR: {tracer.upper()} PET processing failed for {session_id}"
    exit 1
fi

echo "{tracer.upper()} PET processing completed at: $(date)"
"""