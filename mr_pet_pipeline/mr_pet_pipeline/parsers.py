"""
BIDS dataset parsing for MR and PET sessions
"""
import re
import logging
from pathlib import Path
from typing import List, Dict, Tuple, Optional

from .data_models import SubjectSession


class BIDSParser:
    """Parse BIDS dataset for MR and PET sessions"""
    
    def __init__(self, bids_dir: Path, pet_dirs: Dict[str, Optional[Path]]):
        """
        Args:
            bids_dir: Path to BIDS MR data directory
            pet_dirs: Dictionary mapping tracer names to their directory paths
                     e.g., {'tau': Path(...), 'pib': Path(...)}
        """
        self.bids_dir = bids_dir
        self.pet_dirs = pet_dirs
        self.logger = logging.getLogger(__name__)
        
    def parse_subject_session(self, path_str: str) -> Tuple[str, str, float]:
        """
        Parse subject and session from BIDS path, extract age from session
        
        Args:
            path_str: Path string containing subject and session info
            
        Returns:
            Tuple of (subject, session, age)
        """
        pattern = r'sub-([^_/]+).*?ses-(\d+)'
        match = re.search(pattern, path_str)
        
        if not match:
            raise ValueError(f"Could not parse subject/session from: {path_str}")
            
        subject = f"sub-{match.group(1)}"
        session_num = match.group(2)
        session = f"ses-{session_num}"
        
        # Convert session to age (assuming format like 07691 -> 76.91 years)
        if len(session_num) == 5:
            age = float(f"{session_num[:3]}.{session_num[3:]}")
        else:
            # Fallback - try to extract age from other sources
            age = float(session_num) / 100.0
            
        return subject, session, age
    
    def find_mr_sessions(self, require_flair: bool = False) -> List[SubjectSession]:
        """
        Find all MR sessions with T1w and optionally FLAIR images
        
        Args:
            require_flair: If True, only return sessions with FLAIR
            
        Returns:
            List of SubjectSession objects
        """
        sessions = []
        
        for subject_dir in self.bids_dir.glob("sub-*"):
            if not subject_dir.is_dir():
                continue
                
            for session_dir in subject_dir.glob("ses-*"):
                anat_dir = session_dir / "anat"
                if not anat_dir.exists():
                    continue
                
                try:
                    subject, session, age = self.parse_subject_session(str(session_dir))
                except ValueError:
                    self.logger.warning(f"Could not parse session: {session_dir}")
                    continue
                
                # Look for T1w and FLAIR
                t1w_pattern = f"{subject}_{session}_T1w.nii*"
                flair_pattern = f"{subject}_{session}_FLAIR.nii*"
                
                t1w_files = list(anat_dir.glob(t1w_pattern))
                flair_files = list(anat_dir.glob(flair_pattern))
                
                # Apply filtering logic
                if not t1w_files:
                    continue
                if require_flair and not flair_files:
                    continue
                
                session_obj = SubjectSession(
                    subject=subject,
                    session=session,
                    age=age,
                    t1w_file=t1w_files[0],
                    flair_file=flair_files[0] if flair_files else None
                )
                sessions.append(session_obj)
                    
        self.logger.info(f"Found {len(sessions)} MR sessions")
        return sessions
    
    def find_pet_sessions(self, tracers: List[str]) -> Dict[str, List[Dict]]:
        """
        Find PET sessions organized by tracer type
        
        Args:
            tracers: List of tracer types to look for (e.g., ['tau', 'pib'])
            
        Returns:
            Dictionary mapping tracer type to list of session dictionaries
        """
        pet_sessions = {tracer: [] for tracer in tracers}
        
        # Only search directories that are configured for requested tracers
        for tracer in tracers:
            if tracer not in self.pet_dirs:
                self.logger.warning(f"No directory configured for tracer: {tracer}")
                continue
            
            pet_dir = self.pet_dirs[tracer]
            if pet_dir is None:
                self.logger.warning(f"PET directory for {tracer} is None, skipping")
                continue
            
            if not pet_dir.exists():
                self.logger.warning(f"PET directory for {tracer} does not exist: {pet_dir}")
                continue
            
            self.logger.info(f"Searching for {tracer.upper()} PET sessions in: {pet_dir}")
            
            # Search this tracer's directory
            for subject_dir in pet_dir.glob("sub-*"):
                if not subject_dir.is_dir():
                    continue
                    
                for session_dir in subject_dir.glob("ses-*"):
                    pet_data_dir = session_dir / "pet"
                    if not pet_data_dir.exists():
                        continue
                    
                    try:
                        subject, session, age = self.parse_subject_session(str(session_dir))
                    except ValueError:
                        continue
                    
                    # Find PET files in this directory
                    for pet_file in pet_data_dir.glob("*.nii*"):
                        tracer_type = self._classify_pet_tracer(pet_file)
                        # Only add if it matches the tracer we're looking for
                        if tracer_type == tracer:
                            pet_sessions[tracer].append({
                                'subject': subject,
                                'session': session,
                                'age': age,
                                'pet_file': pet_file,
                                'tracer': tracer_type
                            })
        
        for tracer, sessions in pet_sessions.items():
            self.logger.info(f"Found {len(sessions)} {tracer.upper()} PET sessions")
        
        return pet_sessions
    
    def _classify_pet_tracer(self, pet_file: Path) -> Optional[str]:
        """
        Classify PET tracer from filename
        
        Args:
            pet_file: Path to PET file
            
        Returns:
            Tracer type string or None if not recognized
        """
        filename_lower = pet_file.name.lower()
        
        if 'mk6240' in filename_lower or 'tau' in filename_lower:
            return 'tau'
        elif 'pib' in filename_lower:
            return 'pib'
        
        return None