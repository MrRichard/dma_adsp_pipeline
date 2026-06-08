"""
Main orchestrator for MR-PET processing pipeline
"""
import logging
import shutil
import json
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

from .config import PipelineConfig
from .data_models import SubjectSession
from .parsers import BIDSParser
from .matching import SessionMatcher
from .job_generator import SLURMJobGenerator


class PipelineOrchestrator:
    """Main orchestrator for the MR-PET processing pipeline"""
    
    def __init__(self, config: PipelineConfig):
        self.config = config
        self.logger = self._setup_logging()
        
        # Initialize components
        self.bids_parser = BIDSParser(config.bids_dir, config.pet_dirs)
        self.session_matcher = SessionMatcher(config.max_age_difference)
        self.job_generator = SLURMJobGenerator(config)
        
    def _setup_logging(self) -> logging.Logger:
        """Setup logging configuration"""
        log_dir = self.config.output_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        
        log_level = getattr(logging, self.config.logging.get('level', 'INFO'))
        
        handlers = [logging.StreamHandler()]
        if self.config.logging.get('save_logs', True):
            log_file = log_dir / f"pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
            handlers.append(logging.FileHandler(log_file))
        
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=handlers
        )
        
        return logging.getLogger(__name__)
    
    def run_pipeline(
        self,
        post_recon_only: bool = False,
        pet_only: bool = False,
        all_structurals: bool = False,
        incomplete_only: bool = False,
        subjects: Optional[List[str]] = None,
        limit: Optional[int] = None,
    ) -> Dict[str, List[Path]]:
        """
        Run the complete MR-PET processing pipeline

        Args:
            post_recon_only: If True, only generate post-recon jobs (additional modules, Brainnetome, PET)
            pet_only: If True, only generate PET processing jobs (no FreeSurfer recon)

        Returns:
            Dictionary of job files by category
        """
        self.logger.info("=" * 80)
        mode_log = {
            (True, False, False): "Starting MR-PET Pipeline (POST-RECON MODE)",
            (False, True, False): "Starting MR-PET Pipeline (PET-ONLY MODE)",
            (False, False, True): "Starting MR Processing Pipeline (STRUCTURAL ONLY MODE)",
        }.get((post_recon_only, pet_only, self.config.structural_only), "Starting MR-PET Processing Pipeline")
        self.logger.info(mode_log)
        self.logger.info("=" * 80)

        # Validate inputs
        self.logger.info("Step 0: Validating configuration")
        self._validate_inputs()

        # Step 1: Parse BIDS dataset
        self.logger.info("Step 1: Parsing BIDS dataset for MR sessions")
        require_flair = self.config.validation.get('require_flair', False)
        mr_sessions = self.bids_parser.find_mr_sessions(require_flair=require_flair)

        if not mr_sessions:
            raise ValueError("No MR sessions found in BIDS directory")

        # Determine which sessions to use based on mode
        if self.config.structural_only or all_structurals or incomplete_only:
            self.logger.info("Skipping PET matching - including all MR structural sessions")
            matched_sessions = mr_sessions
        else:
            # Standard mode: find and match PET sessions
            self.logger.info("Step 2: Finding PET sessions")
            pet_sessions = self.bids_parser.find_pet_sessions(self.config.tracers)
            if not any(pet_sessions.values()):
                raise ValueError("No PET sessions found")
            self.logger.info("Step 3: Matching MR and PET sessions")
            matched_sessions = self.session_matcher.match_sessions(mr_sessions, pet_sessions)
            if not matched_sessions:
                raise ValueError("No matching sessions found between MR and PET data")
        
        # Step 4: Filter sessions based on processing status
        self.logger.info("Step 4: Filtering sessions based on processing status")
        sessions_to_process = self._filter_sessions_for_processing(
            matched_sessions, post_recon_only, pet_only, incomplete_only
        )

        if not sessions_to_process:
            self.logger.warning("No sessions found that meet the criteria for processing.")
            return {'freesurfer': [], 'pet': [], 'post_recon': []}

        # Apply subject filter
        if subjects:
            normalized = [s if s.startswith('sub-') else f'sub-{s}' for s in subjects]
            sessions_to_process = [s for s in sessions_to_process if s.subject in normalized]
            self.logger.info(f"Subject filter applied: {len(sessions_to_process)} session(s) selected")
            if not sessions_to_process:
                self.logger.warning(f"No sessions matched subjects: {subjects}")
                return {'freesurfer': [], 'pet': [], 'post_recon': []}

        # Apply batch size limit
        if limit and len(sessions_to_process) > limit:
            sessions_to_process = sessions_to_process[:limit]
            self.logger.info(f"Limit applied: processing first {limit} session(s)")

        # Step 5: Generate processing jobs
        self.logger.info("Step 5: Generating SLURM jobs")
        jobs_by_session = self._generate_all_jobs(
            sessions_to_process, post_recon_only, pet_only, incomplete_only
        )
        
        # Step 6: Create submission script
        self.logger.info("Step 6: Creating job submission script")
        submission_script = self._create_submission_script(jobs_by_session)

        # Create provenance file
        self._create_provenance_file(sessions_to_process)

        # Step 7: Generate summary report
        self.logger.info("Step 7: Generating summary report")
        all_job_files = {
            'freesurfer': [job for jobs in jobs_by_session.values() for job in jobs.get('freesurfer', [])],
            'pet': [job for jobs in jobs_by_session.values() for job in jobs.get('pet', [])],
            'post_recon': [job for jobs in jobs_by_session.values() for job in jobs.get('post_recon', [])],
        }
        self._generate_summary_report(matched_sessions, sessions_to_process, all_job_files)
        
        self.logger.info("=" * 80)
        self.logger.info("Pipeline setup completed successfully")
        total_jobs = sum(len(j) for j in all_job_files.values())
        self.logger.info(f"Total jobs created: {total_jobs}")
        if submission_script:
            self.logger.info(f"Submission script: {submission_script}")
        self.logger.info("=" * 80)
        
        return all_job_files

    def _validate_inputs(self):
        """Validate all required paths and dependencies"""
        errors = self.config.validate()
        if errors:
            raise ValueError("Configuration validation failed:\n" + "\n".join(f"  - {e}" for e in errors))
        self.logger.info("Input validation completed successfully")

    def _filter_sessions_for_processing(
        self,
        sessions: List[SubjectSession],
        post_recon_only: bool,
        pet_only: bool,
        incomplete_only: bool,
    ) -> List[SubjectSession]:
        """Filter sessions based on recon status and processing mode."""
        fs_subjects_dir = self.config.output_dir / "freesurfer"
        sessions_to_process = []
        skipped_sessions = 0

        for session in sessions:
            session_id = session.get_session_id()
            fs_output_dir = fs_subjects_dir / session_id
            completion_flag = fs_output_dir / "freesurfer_completed.flag"
            recon_completed = completion_flag.exists()

            if incomplete_only:
                if not recon_completed:
                    self.logger.info(f"  Incomplete recon, scheduling: {session_id}")
                    if fs_output_dir.exists():
                        self.logger.info(f"  Removing existing incomplete directory: {fs_output_dir}")
                        shutil.rmtree(fs_output_dir)
                    sessions_to_process.append(session)
                else:
                    skipped_sessions += 1
                continue

            if post_recon_only or pet_only:
                if recon_completed:
                    sessions_to_process.append(session)
                else:
                    self.logger.info(f"  Skipping {session_id} - FreeSurfer recon not completed")
                    skipped_sessions += 1
            else:
                if recon_completed and not self.config.force_reprocess:
                    self.logger.info(f"  Skipping {session_id} - recon already completed")
                    skipped_sessions += 1
                else:
                    if recon_completed and self.config.force_reprocess:
                        self.logger.info(f"  Reprocessing {session_id} (force_reprocess=true)")
                    sessions_to_process.append(session)
        
        self.logger.info(f"Sessions to process: {len(sessions_to_process)}")
        self.logger.info(f"Sessions skipped: {skipped_sessions}")
        return sessions_to_process

    def _generate_all_jobs(
        self, 
        sessions_to_process: List[SubjectSession],
        post_recon_only: bool,
        pet_only: bool,
        incomplete_only: bool
    ) -> Dict[str, Dict[str, List[Path]]]:
        """Generate all SLURM job files, organized by session."""
        jobs_by_session = {}

        for session in sessions_to_process:
            session_id = session.get_session_id()
            jobs_by_session[session_id] = {'freesurfer': [], 'pet': [], 'post_recon': []}
            
            session.output_dir = self.config.output_dir / session_id
            session.output_dir.mkdir(parents=True, exist_ok=True)
            
            mode_flags = (post_recon_only, pet_only, self.config.structural_only, incomplete_only)
            
            if any(mode_flags):
                if post_recon_only:
                    job = self.job_generator.create_post_recon_job(session)
                    jobs_by_session[session_id]['post_recon'].append(job)
                elif pet_only and session.pet_files:
                    jobs = self.job_generator.create_pet_processing_job(session)
                    jobs_by_session[session_id]['pet'].extend(jobs)
                elif incomplete_only or self.config.structural_only:
                    job = self.job_generator.create_freesurfer_job(session)
                    jobs_by_session[session_id]['freesurfer'].append(job)
            else:
                # Normal mode
                fs_job = self.job_generator.create_freesurfer_job(session)
                jobs_by_session[session_id]['freesurfer'].append(fs_job)
                if session.pet_files:
                    pet_jobs = self.job_generator.create_pet_processing_job(session)
                    jobs_by_session[session_id]['pet'].extend(pet_jobs)

        return jobs_by_session

    def _create_submission_script(self, jobs_by_session: Dict[str, Dict[str, List[Path]]]) -> Optional[Path]:
        """Create a script to submit all jobs with proper dependencies."""
        if not any(jobs_by_session.values()):
            self.logger.info("No jobs to submit - skipping submission script creation")
            return None

        script_path = self.config.output_dir / "submit_all_jobs.sh"
        script_content = f"""#!/bin/bash
# MR-PET Pipeline Job Submission Script
# Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
echo "Submitting all jobs with dependencies..."
echo "="*60

"""
        for session_id, jobs in jobs_by_session.items():
            fs_job = jobs.get('freesurfer', [])[0] if jobs.get('freesurfer') else None
            pet_jobs = jobs.get('pet', [])
            post_recon_job = jobs.get('post_recon', [])[0] if jobs.get('post_recon') else None
            
            script_content += f"# Session: {session_id}\n"

            # Handle job submission logic based on job type
            if fs_job:
                script_content += f"FS_JOB_ID=$(sbatch --parsable {fs_job})\n"
                script_content += f"echo 'Submitted FreeSurfer job for {session_id}: $FS_JOB_ID'\n"
                if pet_jobs:
                    for pet_job in pet_jobs:
                        script_content += f"PET_JOB_ID=$(sbatch --parsable --dependency=afterok:$FS_JOB_ID {pet_job})\n"
                        script_content += f"echo '  - Submitted PET job dependent on $FS_JOB_ID: $PET_JOB_ID'\n"
            elif post_recon_job:
                script_content += f"POST_RECON_JOB_ID=$(sbatch --parsable {post_recon_job})\n"
                script_content += f"echo 'Submitted Post-Recon job for {session_id}: $POST_RECON_JOB_ID'\n"
            elif pet_jobs: # PET-only mode
                for pet_job in pet_jobs:
                    script_content += f"PET_JOB_ID=$(sbatch --parsable {pet_job})\n"
                    script_content += f"echo 'Submitted PET-only job for {session_id}: $PET_JOB_ID'\n"

            script_content += "\n"

        script_content += f"""
echo "="*60
echo "All jobs submitted."
echo "Monitor job status with: squeue -u $USER"
echo "Check logs in: {self.config.output_dir}/jobs/"
"""
        
        script_path.write_text(script_content)
        script_path.chmod(0o755)
        
        self.logger.info(f"Created submission script: {script_path}")
        return script_path
    
    def _create_provenance_file(self, sessions: List[SubjectSession]):
        """Create a text file mapping PET files to the T1w file used for processing"""
        if not self.config.provenance_file:
            return

        with open(self.config.provenance_file, 'w') as f:
            f.write("PET_File,T1w_File\n")
            for session in sessions:
                if session.pet_files:
                    for tracer, pet_file in session.pet_files.items():
                        f.write(f"{pet_file},{session.t1w_file}\n")
        self.logger.info(f"Provenance file created at: {self.config.provenance_file}")
    
    
    def _generate_summary_report(self, all_sessions: List[SubjectSession],
                                sessions_to_process: List[SubjectSession],
                                job_files: Dict[str, List[Path]]):
        """Generate summary report of pipeline setup"""
        summary_path = self.config.output_dir / "pipeline_summary.json"
        
        summary = {
            'pipeline_info': {
                'creation_date': datetime.now().isoformat(),
                'mode': 'structural_only' if self.config.structural_only else 'mr_pet',
                'bids_dir': str(self.config.bids_dir),
                'pet_dirs': {k: str(v) if v else None for k, v in self.config.pet_dirs.items()},
                'output_dir': str(self.config.output_dir),
                'tracers': self.config.tracers if not self.config.structural_only else [],
                'max_age_difference': self.config.max_age_difference,
                'run_brainnetome': self.config.run_brainnetome,
                'run_additional_modules': self.config.run_additional_modules,
                'run_pvc': self.config.run_pvc,
                'force_reprocess': self.config.force_reprocess
            },
            'session_summary': {
                'total_sessions_found': len(all_sessions),
                'sessions_to_process': len(sessions_to_process),
                'sessions_skipped_existing': len(all_sessions) - len(sessions_to_process),
                'sessions_with_t1w': sum(1 for s in all_sessions if s.t1w_file),
                'sessions_with_flair': sum(1 for s in all_sessions if s.flair_file),
            },
            'job_summary': {
                'freesurfer_jobs': len(job_files.get('freesurfer', [])),
                'pet_jobs': len(job_files.get('pet', [])),
                'post_recon_jobs': len(job_files.get('post_recon', [])),
                'total_jobs': len(job_files.get('freesurfer', [])) + len(job_files.get('pet', [])) + len(job_files.get('post_recon', []))
            },
            'sessions': []
        }
        
        # Add PET statistics only if not structural_only
        if not self.config.structural_only:
            summary['session_summary'].update({
                'sessions_with_tau': sum(1 for s in all_sessions if 'tau' in s.pet_files),
                'sessions_with_pib': sum(1 for s in all_sessions if 'pib' in s.pet_files),
                'sessions_with_both_tracers': sum(1 for s in all_sessions if len(s.pet_files) >= 2)
            })
        
        # Add detailed session information
        for session in sessions_to_process:
            session_info = {
                'subject': session.subject,
                'session': session.session,
                'age': session.age,
                't1w_file': str(session.t1w_file) if session.t1w_file else None,
                'flair_file': str(session.flair_file) if session.flair_file else None,
                'pet_files': {k: str(v) for k, v in session.pet_files.items()},
                'output_dir': str(session.output_dir) if session.output_dir else None
            }
            summary['sessions'].append(session_info)
        
        with open(summary_path, 'w') as f:
            json.dump(summary, f, indent=2)
        
        self.logger.info(f"Summary report saved to: {summary_path}")
        
        # Also create a simple text summary
        text_summary_path = self.config.output_dir / "pipeline_summary.txt"
        with open(text_summary_path, 'w') as f:
            f.write("MR-PET Processing Pipeline Summary\n")
            f.write("=" * 80 + "\n\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Mode: {'Structural Only' if self.config.structural_only else 'MR-PET'}\n\n")
            f.write("Configuration:\n")
            f.write(f"  BIDS Directory: {self.config.bids_dir}\n")
            if not self.config.structural_only:
                f.write("  PET Directories:\n")
                for tracer, path in self.config.pet_dirs.items():
                    if path:
                        f.write(f"    {tracer.upper()}: {path}\n")
                    else:
                        f.write(f"    {tracer.upper()}: Not configured\n")
                f.write(f"  Tracers: {', '.join(self.config.tracers)}\n")
                f.write(f"  Max Age Difference: {self.config.max_age_difference} years\n")
            f.write(f"  Output Directory: {self.config.output_dir}\n")
            f.write(f"  Force Reprocess: {self.config.force_reprocess}\n\n")
            f.write("Session Statistics:\n")
            f.write(f"  Total Sessions Found: {summary['session_summary']['total_sessions_found']}\n")
            f.write(f"  Sessions to Process: {summary['session_summary']['sessions_to_process']}\n")
            f.write(f"  Sessions Skipped (already completed): {summary['session_summary']['sessions_skipped_existing']}\n")
            f.write(f"  Sessions with FLAIR: {summary['session_summary']['sessions_with_flair']}\n")
            if not self.config.structural_only:
                f.write(f"  Sessions with Tau PET: {summary['session_summary']['sessions_with_tau']}\n")
                f.write(f"  Sessions with PIB PET: {summary['session_summary']['sessions_with_pib']}\n")
                f.write(f"  Sessions with Both Tracers: {summary['session_summary']['sessions_with_both_tracers']}\n")
            f.write("\nJobs Created:\n")
            f.write(f"  FreeSurfer Jobs: {summary['job_summary']['freesurfer_jobs']}\n")
            f.write(f"  Post-Recon Jobs: {summary['job_summary']['post_recon_jobs']}\n")
            if not self.config.structural_only:
                f.write(f"  PET Processing Jobs: {summary['job_summary']['pet_jobs']}\n")
            f.write(f"  Total Jobs: {summary['job_summary']['total_jobs']}\n")
        
        self.logger.info(f"Text summary saved to: {text_summary_path}")
