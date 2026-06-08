#!/usr/bin/env python3
"""
MR-PET Pipeline Main Entry Point

This script orchestrates a complete pipeline for processing BIDS MR and PET data.

Usage:
    python run_pipeline.py --config config.yaml
    python run_pipeline.py --config test_input.yaml --dry-run
"""

import argparse
import sys
from pathlib import Path

from mr_pet_pipeline import load_config, PipelineOrchestrator


def main():
    """Main entry point for the pipeline"""
    parser = argparse.ArgumentParser(
        description="MR-PET Processing Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Run with configuration file
    python run_pipeline.py --config config/my_config.yaml
    
    # Dry run (setup only, don't submit jobs)
    python run_pipeline.py --config config/my_config.yaml --dry-run
    
    # Verbose output
    python run_pipeline.py --config config/my_config.yaml --verbose
        """
    )
    
    parser.add_argument(
        '--config',
        type=Path,
        required=True,
        help='Path to YAML configuration file'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Setup pipeline without submitting jobs'
    )
    
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose output'
    )
    
    parser.add_argument(
        '--validate-only',
        action='store_true',
        help='Only validate configuration and inputs, do not generate jobs'
    )

    parser.add_argument(
        '--post-recon',
        action='store_true',
        help='Generate jobs for post-FreeSurfer steps only (additional modules, Brainnetome, PET processing) for already completed recons'
    )

    parser.add_argument(
        '--pet-only',
        action='store_true',
        help='Generate PET processing jobs only (no FreeSurfer recon jobs). Requires completed FreeSurfer recons.'
    )
    parser.add_argument(
        '--all-structurals',
        action='store_true',
        help='Include all structural reconstructions and skip PET matching (use with --post-recon to re-run post-recon steps on all completed sessions)'
    )
    parser.add_argument(
        '--incomplete-recon-only',
        action='store_true',
        help='Select only incomplete or missing FreeSurfer reconstructions; remove any existing outputs and restart recon-all with post-processing'
    )
    parser.add_argument(
        '--run-structurals-only',
        action='store_true',
        help='Run only structural processing, ignoring config file settings for PET'
    )
    parser.add_argument(
        '--subject',
        nargs='+',
        metavar='SUBJECT_ID',
        help='Limit processing to one or more subjects (e.g. sub-1001 or 1001). Multiple IDs separated by spaces.'
    )
    parser.add_argument(
        '--limit',
        type=int,
        metavar='N',
        help='Limit processing to the first N sessions (useful for testing)'
    )

    args = parser.parse_args()

    # Check for mutually exclusive flags
    if args.post_recon and args.pet_only:
        print("Error: --post-recon and --pet-only are mutually exclusive")
        return 1
    if args.all_structurals and not args.post_recon:
        print("Error: --all-structurals must be used with --post-recon")
        return 1
    if args.incomplete_recon_only and (args.post_recon or args.pet_only):
        print("Error: --incomplete-recon-only cannot be combined with --post-recon or --pet-only")
        return 1

    # Check if config file exists
    if not args.config.exists():
        print(f"Error: Configuration file not found: {args.config}")
        return 1
    
    try:
        # Load configuration
        print(f"Loading configuration from: {args.config}")
        config = load_config(args.config)
        
        # Update logging level if verbose
        if args.verbose:
            config.logging['level'] = 'DEBUG'
        
        # Override config if structurals-only flag is set
        if args.run_structurals_only:
            config.structural_only = True
            print("Running in structural-only mode due to --run-structurals-only flag")
        
        # Validate configuration
        errors = config.validate()
        if errors:
            print("\nConfiguration validation failed:")
            for error in errors:
                print(f"  ❌ {error}")
            return 1
        
        print("✓ Configuration validated successfully")
        
        if args.validate_only:
            print("\nValidation complete. Exiting (--validate-only specified)")
            return 0
        
        # Create output directory
        config.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize and run pipeline
        print("\nInitializing pipeline orchestrator...")
        orchestrator = PipelineOrchestrator(config)

        print("\nRunning pipeline setup...")
        job_files = orchestrator.run_pipeline(
            post_recon_only=args.post_recon,
            pet_only=args.pet_only,
            all_structurals=args.all_structurals,
            incomplete_only=args.incomplete_recon_only,
            subjects=args.subject,
            limit=args.limit,
        )
        
        # Print summary
        print("\n" + "=" * 80)
        print("PIPELINE SETUP COMPLETED SUCCESSFULLY")
        print("=" * 80)
        print(f"\n📁 Output directory: {config.output_dir}")
        print(f"\n📊 Jobs created:")
        print(f"   - FreeSurfer jobs: {len(job_files.get('freesurfer', []))}")
        print(f"   - Post-recon jobs: {len(job_files.get('post_recon', []))}")
        print(f"   - PET jobs: {len(job_files.get('pet', []))}")
        print(f"   - Total: {len(job_files.get('freesurfer', [])) + len(job_files.get('post_recon', [])) + len(job_files.get('pet', []))}")
        
        print(f"\n📋 Summary reports:")
        print(f"   - JSON: {config.output_dir}/pipeline_summary.json")
        print(f"   - Text: {config.output_dir}/pipeline_summary.txt")
        
        submission_script = config.output_dir / "submit_all_jobs.sh"
        if submission_script.exists():
            print(f"\n🚀 To submit all jobs, run:")
            print(f"   {submission_script}")
            
            if args.dry_run:
                print("\n⚠️  DRY RUN MODE: Jobs created but not submitted")
                print("   Remove --dry-run flag to actually submit jobs")
        
        print("\n" + "=" * 80)
        
        return 0
        
    except ValueError as e:
        print(f"\n❌ Error: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
