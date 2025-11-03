"""
Main orchestrator for MR-PET processing pipeline
"""
import logging
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
    
    def run_pipeline(self, post_recon_only: bool = False, pet_only: bool = False) -> Dict[str, List[Path]]:
        """
        Run the complete MR-PET processing pipeline

        Args:
            post_recon_only: If True, only generate post-recon jobs (additional modules, Brainnetome, PET)
            pet_only: If True, only generate PET processing jobs (no FreeSurfer recon)

        Returns:
            Dictionary of job files by category
        """
        self.logger.info("=" * 80)
        if post_recon_only:
            self.logger.info("Starting MR-PET Pipeline (POST-RECON MODE)")
        elif pet_only:
            self.logger.info("Starting MR-PET Pipeline (PET-ONLY MODE)")
        elif self.config.structural_only:
            self.logger.info("Starting MR Processing Pipeline (STRUCTURAL ONLY MODE)")
        else:
            self.logger.info("Starting MR-PET Processing Pipeline")
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
        
        # Determine final sessions to process
        if self.config.structural_only:
            # Structural only mode: use all MR sessions
            self.logger.info("Running in structural-only mode - skipping PET matching")
            matched_sessions = mr_sessions
        else:
            # Standard mode: match with PET
            # Step 2: Find PET sessions
            self.logger.info("Step 2: Finding PET sessions")
            pet_sessions = self.bids_parser.find_pet_sessions(self.config.tracers)
            
            # Check if any PET sessions found
            total_pet = sum(len(sessions) for sessions in pet_sessions.values())
            if total_pet == 0:
                raise ValueError("No PET sessions found")
            
            # Step 3: Match sessions
            self.logger.info("Step 3: Matching MR and PET sessions")
            matched_sessions = self.session_matcher.match_sessions(mr_sessions, pet_sessions)
            
            if not matched_sessions:
                raise ValueError("No matching sessions found between MR and PET data")
        
        # Step 4: Check for existing FreeSurfer recons
        self.logger.info("Step 4: Checking for existing FreeSurfer recons")
        sessions_to_process = self._filter_existing_recons(matched_sessions, post_recon_only, pet_only)

        if not sessions_to_process:
            if post_recon_only:
                self.logger.warning("No sessions with completed FreeSurfer recons found for post-recon processing.")
            elif pet_only:
                self.logger.warning("No sessions with completed FreeSurfer recons found for PET-only processing.")
            else:
                self.logger.warning("All sessions have completed FreeSurfer recons. No new jobs to generate.")
                self.logger.info("Use force_reprocess: true in config to reprocess existing sessions")
            return {'freesurfer': [], 'pet': [], 'post_recon': []}
        
        # Step 5: Generate processing jobs
        self.logger.info("Step 5: Generating SLURM jobs")
        job_files = self._generate_all_jobs(sessions_to_process, post_recon_only, pet_only)
        
        # Step 6: Create submission script
        self.logger.info("Step 6: Creating job submission script")
        submission_script = self._create_submission_script(job_files)
        
        # Step 7: Generate summary report
        self.logger.info("Step 7: Generating summary report")
        self._generate_summary_report(matched_sessions, sessions_to_process, job_files)
        
        self.logger.info("=" * 80)
        self.logger.info("Pipeline setup completed successfully")
        self.logger.info(f"Total jobs created: {len(job_files['freesurfer']) + len(job_files['pet'])}")
        if submission_script:
            self.logger.info(f"Submission script: {submission_script}")
        self.logger.info("=" * 80)
        
        return job_files
    
    def _validate_inputs(self):
        """Validate all required paths and dependencies"""
        errors = self.config.validate()
        
        if errors:
            error_msg = "Configuration validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
            raise ValueError(error_msg)
        
        self.logger.info("Input validation completed successfully")
    
    def _filter_existing_recons(self, sessions: List[SubjectSession],
                                post_recon_only: bool = False,
                                pet_only: bool = False) -> List[SubjectSession]:
        """
        Filter sessions based on FreeSurfer recon status

        Args:
            sessions: List of all sessions
            post_recon_only: If True, only return sessions WITH completed recons
            pet_only: If True, only return sessions WITH completed recons

        Returns:
            List of sessions that need processing
        """
        sessions_to_process = []
        skipped_sessions = []

        fs_subjects_dir = self.config.output_dir / "freesurfer"

        for session in sessions:
            session_id = session.get_session_id()
            fs_output_dir = fs_subjects_dir / session_id
            completion_flag = fs_output_dir / "freesurfer_completed.flag"

            # Check if FreeSurfer has been completed
            recon_completed = completion_flag.exists()

            if post_recon_only or pet_only:
                # For post-recon or PET-only modes, we ONLY process sessions with completed recons
                if recon_completed:
                    self.logger.info(f"  ✓ Found completed recon: {session_id}")
                    sessions_to_process.append(session)
                else:
                    self.logger.info(f"  ✗ Skipping {session_id} - FreeSurfer recon not completed")
                    skipped_sessions.append(session)
            else:
                # Normal mode: skip completed recons unless force_reprocess
                if recon_completed and not self.config.force_reprocess:
                    self.logger.info(f"  ✓ Skipping {session_id} - FreeSurfer recon already completed")
                    skipped_sessions.append(session)
                else:
                    if fs_output_dir.exists() and self.config.force_reprocess:
                        self.logger.info(f"  ! Will reprocess {session_id} (force_reprocess=true)")
                    sessions_to_process.append(session)

        self.logger.info(f"Sessions to process: {len(sessions_to_process)}")
        self.logger.info(f"Sessions skipped: {len(skipped_sessions)}")

        return sessions_to_process
    
    def _generate_all_jobs(self, matched_sessions: List[SubjectSession],
                          post_recon_only: bool = False,
                          pet_only: bool = False) -> Dict[str, List[Path]]:
        """Generate all SLURM job files"""
        job_files = {
            'freesurfer': [],
            'pet': [],
            'post_recon': []
        }

        for session in matched_sessions:
            # Set output directory for session (simplified structure)
            session.output_dir = self.config.output_dir / session.get_session_id()
            session.output_dir.mkdir(parents=True, exist_ok=True)

            if post_recon_only:
                # Generate post-recon job (additional modules + Brainnetome + PET)
                post_recon_job = self.job_generator.create_post_recon_job(session)
                job_files['post_recon'].append(post_recon_job)
            elif pet_only:
                # Generate PET jobs only
                if session.pet_files:
                    pet_jobs = self.job_generator.create_pet_processing_job(session)
                    job_files['pet'].extend(pet_jobs)
            else:
                # Normal mode: Generate FreeSurfer job
                fs_job = self.job_generator.create_freesurfer_job(session)
                job_files['freesurfer'].append(fs_job)

                # Generate PET jobs if PET files exist and not in structural_only mode
                if not self.config.structural_only and session.pet_files:
                    pet_jobs = self.job_generator.create_pet_processing_job(session)
                    job_files['pet'].extend(pet_jobs)

        if post_recon_only:
            self.logger.info(f"Created {len(job_files['post_recon'])} post-recon jobs")
        elif pet_only:
            self.logger.info(f"Created {len(job_files['pet'])} PET-only jobs")
        else:
            self.logger.info(f"Created {len(job_files['freesurfer'])} FreeSurfer jobs")
            if not self.config.structural_only:
                self.logger.info(f"Created {len(job_files['pet'])} PET processing jobs")

        return job_files
    
    def _create_submission_script(self, job_files: Dict[str, List[Path]]) -> Optional[Path]:
        """Create script to submit all jobs (without automatic dependencies as requested)"""
        total_jobs = len(job_files.get('freesurfer', [])) + len(job_files.get('pet', [])) + len(job_files.get('post_recon', []))
        if total_jobs == 0:
            self.logger.info("No jobs to submit - skipping submission script creation")
            return None
        
        script_path = self.config.output_dir / "submit_all_jobs.sh"

        # Determine mode for header
        mode = "POST-RECON" if job_files.get('post_recon') else ("PET-ONLY" if (job_files.get('pet') and not job_files.get('freesurfer')) else "FULL")

        script_content = f"""#!/bin/bash
# MR-PET Pipeline Job Submission Script
# Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
# Mode: {mode}
# NOTE: Jobs must be run manually in the order you want them

echo "Job submission script for {mode} mode"
echo "="*60
"""

        # Add FreeSurfer jobs
        if job_files.get('freesurfer'):
            script_content += f"""
echo "FreeSurfer jobs ({len(job_files['freesurfer'])}):"
"""
            for fs_job in job_files['freesurfer']:
                session_id = '_'.join(fs_job.stem.split('_')[:2])
                script_content += f'echo "  sbatch {fs_job}  # {session_id}"\n'

        # Add post-recon jobs
        if job_files.get('post_recon'):
            script_content += f"""
echo ""
echo "Post-recon jobs ({len(job_files['post_recon'])}):"
"""
            for pr_job in job_files['post_recon']:
                session_id = '_'.join(pr_job.stem.split('_')[:2])
                script_content += f'echo "  sbatch {pr_job}  # {session_id}"\n'

        # Add PET jobs
        if job_files.get('pet'):
            script_content += f"""
echo ""
echo "PET processing jobs ({len(job_files['pet'])}):"
"""
            for pet_job in job_files['pet']:
                parts = pet_job.stem.split('_')
                session_id = f"{parts[0]}_{parts[1]}"
                tracer = parts[2] if len(parts) > 2 else "pet"
                script_content += f'echo "  sbatch {pet_job}  # {session_id} - {tracer.upper()}"\n'

        script_content += f"""
echo ""
echo "="*60
echo "NOTE: These jobs are listed for reference."
echo "Submit them manually in the order you prefer."
echo "Monitor job status with: squeue -u $USER"
echo "Check logs in: {self.config.output_dir}/jobs/"
"""
        
        script_path.write_text(script_content)
        script_path.chmod(0o755)
        
        self.logger.info(f"Created submission script: {script_path}")
        return script_path
    
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