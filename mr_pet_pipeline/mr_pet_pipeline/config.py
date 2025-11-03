"""
Configuration management for MR-PET pipeline
"""
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any, Optional


@dataclass
class SLURMConfig:
    """SLURM configuration settings"""
    partition: str = "defq"
    account: str = "ansir-users"
    freesurfer: Dict[str, Any] = field(default_factory=lambda: {
        'time': '24:00:00',
        'memory': '64G',
        'cpus': 8,
        'gpus': 1
    })
    pet: Dict[str, Any] = field(default_factory=lambda: {
        'time': '4:00:00',
        'memory': '16G',
        'cpus': 4,
        'gpus': 0
    })
    aggregation: Dict[str, Any] = field(default_factory=lambda: {
        'time': '2:00:00',
        'memory': '8G',
        'cpus': 2
    })


@dataclass
class PipelineConfig:
    """Main configuration class for pipeline settings"""
    # Core directories
    bids_dir: Path
    pet_dirs: Dict[str, Optional[Path]]  # e.g., {'tau': Path(...), 'pib': Path(...)}
    output_dir: Path
    
    # Tool paths (required)
    container_path: Path
    freesurfer_license: Path
    
    # Optional tool paths
    brainnetome_dir: Optional[Path] = None
    atlas_template_path: Optional[Path] = None
    spm_path: Optional[Path] = None
    c3d_path: Optional[Path] = None
    petpvc_path: Optional[Path] = None
    matlab_scripts_path: Optional[Path] = None
    matlab_module: str = "matlab/2024b"  # Module to load for MATLAB scripts
    antsaffine_path: Optional[Path] = None
    resample_path: Optional[Path] = None
    
    # Processing options
    structural_only: bool = False  # NEW: Process only MR data, skip PET
    max_age_difference: float = 5.0
    tracers: List[str] = field(default_factory=lambda: ['tau', 'pib'])
    force_reprocess: bool = False
    run_additional_modules: bool = True
    run_brainnetome: bool = True
    run_pvc: bool = False
    
    # SLURM settings
    slurm: SLURMConfig = field(default_factory=SLURMConfig)
    
    # Output settings
    outputs: Dict[str, bool] = field(default_factory=lambda: {
        'save_qc_images': True,
        'save_combined_csv': True,
        'cleanup_temp_files': True
    })
    
    # QC settings
    qc: Dict[str, bool] = field(default_factory=lambda: {
        'generate_qc_images': True
    })
    
    # Logging
    logging: Dict[str, Any] = field(default_factory=lambda: {
        'level': 'INFO',
        'save_logs': True
    })
    
    # Validation
    validation: Dict[str, Any] = field(default_factory=lambda: {
        'require_t1w': True,
        'require_flair': False,
        'min_age': 10,
        'max_age': 100
    })
    
    def __post_init__(self):
        """Convert string paths to Path objects"""
        self.bids_dir = Path(self.bids_dir)
        self.output_dir = Path(self.output_dir)
        self.container_path = Path(self.container_path)
        self.freesurfer_license = Path(self.freesurfer_license).expanduser()
        
        # Handle PET directories (can be dict or single path for backward compatibility)
        if isinstance(self.pet_dirs, dict):
            # Convert each PET directory path
            for tracer, path in self.pet_dirs.items():
                if path is not None:
                    self.pet_dirs[tracer] = Path(path)
        elif isinstance(self.pet_dirs, (str, Path)):
            # Backward compatibility: single pet_dir
            self.pet_dirs = {'tau': Path(self.pet_dirs), 'pib': Path(self.pet_dirs)}
        else:
            # Initialize empty dict if None (allowed in structural_only mode)
            self.pet_dirs = {}
        
        # Convert optional paths
        if self.brainnetome_dir:
            self.brainnetome_dir = Path(self.brainnetome_dir)
        if self.atlas_template_path:
            self.atlas_template_path = Path(self.atlas_template_path)
        if self.spm_path:
            self.spm_path = Path(self.spm_path)
        if self.c3d_path:
            self.c3d_path = Path(self.c3d_path)
        if self.petpvc_path:
            self.petpvc_path = Path(self.petpvc_path)
        if self.matlab_scripts_path:
            self.matlab_scripts_path = Path(self.matlab_scripts_path)
        if self.antsaffine_path:
            self.antsaffine_path = Path(self.antsaffine_path)
        if self.resample_path:
            self.resample_path = Path(self.resample_path)
        
        # Create SLURM config from dict if needed
        if isinstance(self.slurm, dict):
            self.slurm = SLURMConfig(**self.slurm)
    
    def validate(self) -> List[str]:
        """Validate configuration and return list of errors"""
        errors = []
        
        # Check required directories
        if not self.bids_dir.exists():
            errors.append(f"BIDS directory not found: {self.bids_dir}")
        
        # PET validation depends on structural_only mode
        if not self.structural_only:
            # Check PET directories (at least one tracer directory should be specified)
            if not self.pet_dirs:
                errors.append("No PET directories specified. Please configure at least one tracer directory (tau or pib) or set structural_only: true")
            else:
                found_valid_pet_dir = False
                for tracer, path in self.pet_dirs.items():
                    if path is not None:
                        if not path.exists():
                            errors.append(f"PET directory for {tracer} not found: {path}")
                        else:
                            found_valid_pet_dir = True
                
                if not found_valid_pet_dir:
                    errors.append("No valid PET directories found. At least one PET directory must exist or set structural_only: true")
            
            # Validate tracers match configured directories
            valid_tracers = set(self.pet_dirs.keys())
            invalid = set(self.tracers) - valid_tracers
            if invalid:
                errors.append(f"Tracers {invalid} specified but no corresponding PET directory configured")
            
            # Check that specified tracers have valid directories
            for tracer in self.tracers:
                if tracer not in self.pet_dirs or self.pet_dirs[tracer] is None:
                    errors.append(f"Tracer '{tracer}' specified in tracers list but no directory configured")
        else:
            # In structural_only mode, PET directories are optional
            pass
        
        if not self.container_path.exists():
            errors.append(f"Container not found: {self.container_path}")
        if not self.freesurfer_license.exists():
            errors.append(f"FreeSurfer license not found: {self.freesurfer_license}")
        
        # Check Brainnetome if enabled
        if self.run_brainnetome:
            if not self.brainnetome_dir:
                errors.append("Brainnetome enabled but directory not specified")
            elif not self.brainnetome_dir.exists():
                errors.append(f"Brainnetome directory not found: {self.brainnetome_dir}")
            else:
                required_files = ['lh.BN_Atlas.gcs', 'rh.BN_Atlas.gcs']
                for fname in required_files:
                    if not (self.brainnetome_dir / fname).exists():
                        errors.append(f"Required Brainnetome file not found: {fname}")
        
        # Check PVC dependencies if enabled
        if self.run_pvc:
            if not self.petpvc_path:
                errors.append("PVC enabled but petpvc_path not specified")
            elif not self.petpvc_path.exists():
                errors.append(f"PVC enabled but PETPVC executable not found: {self.petpvc_path}")
            else:
                # Check if file is executable
                import os
                if not os.access(self.petpvc_path, os.X_OK):
                    errors.append(f"PETPVC path exists but is not executable: {self.petpvc_path}")
        
        # Validate age range
        if self.validation['min_age'] >= self.validation['max_age']:
            errors.append("Invalid age range in validation settings")
        
        return errors


def load_config(config_path: Path) -> PipelineConfig:
    """Load configuration from YAML file"""
    with open(config_path, 'r') as f:
        config_dict = yaml.safe_load(f)
    
    return PipelineConfig(**config_dict)


def save_config(config: PipelineConfig, output_path: Path):
    """Save configuration to YAML file"""
    # Convert to dict, handling Path objects
    config_dict = {}
    for key, value in config.__dict__.items():
        if isinstance(value, Path):
            config_dict[key] = str(value)
        elif isinstance(value, SLURMConfig):
            config_dict[key] = value.__dict__
        else:
            config_dict[key] = value
    
    with open(output_path, 'w') as f:
        yaml.dump(config_dict, f, default_flow_style=False, sort_keys=False)