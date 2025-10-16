"""
Session matching logic for MR and PET data
"""
import logging
from typing import List, Dict, Tuple

from .data_models import SubjectSession


class SessionMatcher:
    """Match MR and PET sessions based on age/date proximity"""
    
    def __init__(self, max_age_difference: float = 5.0):
        """
        Args:
            max_age_difference: Maximum age difference in years for matching
        """
        self.max_age_difference = max_age_difference
        self.logger = logging.getLogger(__name__)
    
    def match_sessions(self, mr_sessions: List[SubjectSession], 
                      pet_sessions: Dict[str, List[Dict]]) -> List[SubjectSession]:
        """
        Create optimal matches between MR and PET sessions
        
        Args:
            mr_sessions: List of MR sessions
            pet_sessions: Dictionary of PET sessions by tracer type
            
        Returns:
            List of matched SubjectSession objects with PET files added
        """
        matched_sessions = []
        
        # Group MR sessions by subject
        mr_by_subject = self._group_by_subject(mr_sessions)
        
        # Statistics for reporting
        total_possible_matches = 0
        successful_matches = 0
        
        # For each tracer type
        for tracer, tracer_sessions in pet_sessions.items():
            self.logger.info(f"Matching {tracer.upper()} sessions: {len(tracer_sessions)} available")
            
            # Group PET sessions by subject
            pet_by_subject = {}
            for pet_session in tracer_sessions:
                subject = pet_session['subject']
                if subject not in pet_by_subject:
                    pet_by_subject[subject] = []
                pet_by_subject[subject].append(pet_session)
            
            # Find matches for each subject
            common_subjects = set(mr_by_subject.keys()) & set(pet_by_subject.keys())
            self.logger.info(f"Found {len(common_subjects)} subjects with both MR and {tracer.upper()} data")
            
            for subject in common_subjects:
                mr_subj_sessions = mr_by_subject[subject]
                pet_subj_sessions = pet_by_subject[subject]
                
                total_possible_matches += len(mr_subj_sessions) * len(pet_subj_sessions)
                
                # Find best matches for this subject
                best_matches = self._find_best_matches(mr_subj_sessions, pet_subj_sessions, tracer)
                successful_matches += len(best_matches)
                
                for mr_session, pet_session in best_matches:
                    # Find existing session or create new one
                    existing = next((m for m in matched_sessions 
                                   if m.subject == mr_session.subject and m.session == mr_session.session), None)
                    
                    if existing:
                        existing.pet_files[tracer] = pet_session['pet_file']
                        self.logger.debug(f"Added {tracer} to existing session: {existing.get_session_id()}")
                    else:
                        new_session = SubjectSession(
                            subject=mr_session.subject,
                            session=mr_session.session,
                            age=mr_session.age,
                            t1w_file=mr_session.t1w_file,
                            flair_file=mr_session.flair_file,
                            pet_files={tracer: pet_session['pet_file']}
                        )
                        matched_sessions.append(new_session)
                        self.logger.debug(f"Created new matched session: {new_session.get_session_id()}")
        
        self._log_matching_summary(matched_sessions)
        
        return matched_sessions
    
    def _group_by_subject(self, sessions: List[SubjectSession]) -> Dict[str, List[SubjectSession]]:
        """Group sessions by subject ID"""
        grouped = {}
        for session in sessions:
            if session.subject not in grouped:
                grouped[session.subject] = []
            grouped[session.subject].append(session)
        return grouped
    
    def _find_best_matches(self, mr_sessions: List[SubjectSession], 
                          pet_sessions: List[Dict], tracer: str) -> List[Tuple]:
        """
        Find optimal 1:1 matches for one subject
        
        Args:
            mr_sessions: MR sessions for this subject
            pet_sessions: PET sessions for this subject
            tracer: Tracer type
            
        Returns:
            List of (MR session, PET session) tuples
        """
        matches = []
        
        # Calculate all possible matches
        possible_matches = []
        for mr_session in mr_sessions:
            for pet_session in pet_sessions:
                age_diff = abs(mr_session.age - pet_session['age'])
                if age_diff <= self.max_age_difference:
                    possible_matches.append((mr_session, pet_session, age_diff))
        
        if not possible_matches:
            self.logger.debug(f"No valid matches found for subject (age difference > {self.max_age_difference} years)")
            return matches
        
        # Sort by age difference and greedily assign
        possible_matches.sort(key=lambda x: x[2])
        
        used_mr = set()
        used_pet = set()
        
        for mr_session, pet_session, age_diff in possible_matches:
            mr_id = (mr_session.subject, mr_session.session)
            pet_id = (pet_session['subject'], pet_session['session'])
            
            if mr_id not in used_mr and pet_id not in used_pet:
                matches.append((mr_session, pet_session))
                used_mr.add(mr_id)
                used_pet.add(pet_id)
                self.logger.debug(f"Matched {mr_id} to {pet_id} (age diff: {age_diff:.2f} years)")
        
        return matches
    
    def _log_matching_summary(self, matched_sessions: List[SubjectSession]):
        """Log summary statistics about matching results"""
        self.logger.info(f"Session matching completed:")
        self.logger.info(f"  Total matched sessions: {len(matched_sessions)}")
        self.logger.info(f"  Sessions with tau: {sum(1 for s in matched_sessions if 'tau' in s.pet_files)}")
        self.logger.info(f"  Sessions with pib: {sum(1 for s in matched_sessions if 'pib' in s.pet_files)}")
        self.logger.info(f"  Sessions with both tracers: {sum(1 for s in matched_sessions if len(s.pet_files) == 2)}")