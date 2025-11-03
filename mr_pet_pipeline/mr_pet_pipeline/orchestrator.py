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
    
    def run_pipeline(self) -> Dict[str, List[Path]]:
        """
        Run the complete MR-PET processing pipeline
        
        Returns:
            Dictionary of job files by category
        """
        self.logger.info("=" * 80)
        if self.config.structural_only:
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
        sessions_to_process = self._filter_existing_recons(matched_sessions)
        
        if not sessions_to_process:
            self.logger.warning("All sessions have completed FreeSurfer recons. No new jobs to generate.")
            self.logger.info("Use force_reprocess: true in config to reprocess existing sessions")
            return {'freesurfer': [], 'pet': []}
        
        # Step 5: Generate processing jobs
        self.logger.info("Step 5: Generating SLURM jobs")
        job_files = self._generate_all_jobs(sessions_to_process)
        
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
    
    def _filter_existing_recons(self, sessions: List[SubjectSession]) -> List[SubjectSession]:
        """
        Filter out sessions with existing completed FreeSurfer recons
        
        Args:
            sessions: List of all sessions
            
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
            if completion_flag.exists() and not self.config.force_reprocess:
                self.logger.info(f"  ✓ Skipping {session_id} - FreeSurfer recon already completed")
                skipped_sessions.append(session)
            else:
                if fs_output_dir.exists() and self.config.force_reprocess:
                    self.logger.info(f"  ! Will reprocess {session_id} (force_reprocess=true)")
                sessions_to_process.append(session)
        
        self.logger.info(f"Sessions to process: {len(sessions_to_process)}")
        self.logger.info(f"Sessions skipped (already completed): {len(skipped_sessions)}")
        
        return sessions_to_process
    
    def _generate_all_jobs(self, matched_sessions: List[SubjectSession]) -> Dict[str, List[Path]]:
        """Generate all SLURM job files"""
        job_files = {
            'freesurfer': [],
            'pet': []
        }
        
        for session in matched_sessions:
            # Set output directory for session (simplified structure)
            session.output_dir = self.config.output_dir / session.get_session_id()
            session.output_dir.mkdir(parents=True, exist_ok=True)
            
            # Generate FreeSurfer job
            fs_job = self.job_generator.create_freesurfer_job(session)
            job_files['freesurfer'].append(fs_job)
            
            # Generate PET jobs if PET files exist and not in structural_only mode
            if not self.config.structural_only and session.pet_files:
                pet_jobs = self.job_generator.create_pet_processing_job(session)
                job_files['pet'].extend(pet_jobs)
        
        self.logger.info(f"Created {len(job_files['freesurfer'])} FreeSurfer jobs")
        if not self.config.structural_only:
            self.logger.info(f"Created {len(job_files['pet'])} PET processing jobs")
        
        return job_files
    
    def _create_submission_script(self, job_files: Dict[str, List[Path]]) -> Optional[Path]:
        """Create script to submit all jobs with dependencies"""
        if not job_files['freesurfer'] and not job_files['pet']:
            self.logger.info("No jobs to submit - skipping submission script creation")
            return None
        
        script_path = self.config.output_dir / "submit_all_jobs.sh"
        
        script_content = f"""#!/bin/bash
# MR-PET Pipeline Job Submission Script
# Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
# Mode: {'Structural Only' if self.config.structural_only else 'MR-PET'}

echo "Submitting {'MR' if self.config.structural_only else 'MR-PET'} processing pipeline jobs"
echo "Total FreeSurfer jobs: {len(job_files['freesurfer'])}"
"""
        
        if not self.config.structural_only:
            script_content += f"""echo "Total PET jobs: {len(job_files['pet'])}"
"""
        
        script_content += """echo ""

# Submit FreeSurfer jobs first
echo "Submitting FreeSurfer jobs..."
declare -A FS_JOB_MAP

"""
        
        # Add FreeSurfer job submissions with session ID tracking
        for fs_job in job_files['freesurfer']:
            # Extract session ID from job filename
            session_id = '_'.join(fs_job.stem.split('_')[:2])
            script_content += f'FS_JOB_ID=$(sbatch --parsable {fs_job})\n'
            script_content += f'FS_JOB_MAP["{session_id}"]=$FS_JOB_ID\n'
            script_content += f'echo "  [{session_id}] FreeSurfer job: $FS_JOB_ID"\n\n'
        
        # Add PET job submissions with dependencies if not structural_only
        if not self.config.structural_only and job_files['pet']:
            script_content += """
echo ""
echo "Submitting PET processing jobs..."

"""
            
            for pet_job in job_files['pet']:
                # Extract session ID and tracer from filename
                parts = pet_job.stem.split('_')
                session_id = f"{parts[0]}_{parts[1]}"
                tracer = parts[2]
                
                script_content += f'# {session_id} - {tracer.upper()}\n'
                script_content += f'if [ -n "${{FS_JOB_MAP["{session_id}"]}}" ]; then\n'
                script_content += f'    PET_JOB_ID=$(sbatch --parsable --dependency=afterok:${{FS_JOB_MAP["{session_id}"]}} {pet_job})\n'
                script_content += f'    echo "  [{session_id}] {tracer.upper()} PET job: $PET_JOB_ID (depends on ${{FS_JOB_MAP["{session_id}"]}})"   \n'
                script_content += f'else\n'
                script_content += f'    echo "  ERROR: No FreeSurfer job found for {session_id}"\n'
                script_content += f'fi\n\n'
        
        script_content += f"""
echo ""
echo "All jobs submitted successfully"
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
                'freesurfer_jobs': len(job_files['freesurfer']),
                'pet_jobs': len(job_files['pet']),
                'total_jobs': len(job_files['freesurfer']) + len(job_files['pet'])
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
            if not self.config.structural_only:
                f.write(f"  PET Processing Jobs: {summary['job_summary']['pet_jobs']}\n")
            f.write(f"  Total Jobs: {summary['job_summary']['total_jobs']}\n")
        
        self.logger.info(f"Text summary saved to: {text_summary_path}")