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
    
    args = parser.parse_args()
    
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
        job_files = orchestrator.run_pipeline()
        
        # Print summary
        print("\n" + "=" * 80)
        print("PIPELINE SETUP COMPLETED SUCCESSFULLY")
        print("=" * 80)
        print(f"\n📁 Output directory: {config.output_dir}")
        print(f"\n📊 Jobs created:")
        print(f"   - FreeSurfer jobs: {len(job_files['freesurfer'])}")
        print(f"   - PET jobs: {len(job_files['pet'])}")
        print(f"   - Total: {len(job_files['freesurfer']) + len(job_files['pet'])}")
        
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