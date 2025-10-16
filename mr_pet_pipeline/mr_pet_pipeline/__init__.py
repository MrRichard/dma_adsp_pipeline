"""
MR-PET Processing Pipeline Package

A comprehensive pipeline for processing BIDS MR and PET neuroimaging data with
FreeSurfer, including session matching, SLURM job generation, and automated
processing orchestration.
"""

__version__ = "1.0.0"
__author__ = "Your Name"

from .config import PipelineConfig, SLURMConfig, load_config, save_config
from .data_models import SubjectSession
from .parsers import BIDSParser
from .matching import SessionMatcher
from .job_generator import SLURMJobGenerator
from .orchestrator import PipelineOrchestrator

__all__ = [
    'PipelineConfig',
    'SLURMConfig',
    'load_config',
    'save_config',
    'SubjectSession',
    'BIDSParser',
    'SessionMatcher',
    'SLURMJobGenerator',
    'PipelineOrchestrator',
]