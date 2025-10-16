"""
Data models for MR-PET pipeline
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional


@dataclass
class SubjectSession:
    """Data class for subject session information"""
    subject: str
    session: str
    age: float
    t1w_file: Optional[Path] = None
    flair_file: Optional[Path] = None
    pet_files: Dict[str, Path] = field(default_factory=dict)
    output_dir: Optional[Path] = None
    
    def has_tracer(self, tracer: str) -> bool:
        """Check if session has a specific tracer"""
        return tracer in self.pet_files
    
    def get_session_id(self) -> str:
        """Get formatted session identifier"""
        return f"{self.subject}_{self.session}"