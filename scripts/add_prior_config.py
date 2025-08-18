#!/usr/bin/env python3
"""
Generate and insert prior configurations for GraphHopper custom profiles.

Usage:
    # Generate a config template
    uv run ./scripts/add_prior_config.py --create --custom_profile_id 1 -o ./prior_config.yaml

    # Insert priors from config
    uv run ./scripts/add_prior_config.py --insert ./prior_config.yaml
"""

import argparse
import sys
import yaml
from pathlib import Path
from typing import Dict, Any

# Add the parent directory to the Python path to import from r2r_backend
sys.path.insert(0, str(Path(__file__).parent.parent))

from r2r_backend.db.base import SessionLocal
from r2r_backend.db.models import GraphHopperCustomProfile, ProfilePrior
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func


def get_next_prior_version(db_session, profile_id: int) -> int:
    """
    Get the next version number for priors of a specific profile.

    Args:
        db_session: SQLAlchemy session
        profile_id: Custom profile ID

    Returns:
        Next version number (1 if no existing priors)
    """
    max_version = db_session.query(
        func.max(ProfilePrior.version)
    ).filter(
        ProfilePrior.profile_id == profile_id
    ).scalar()

    return (max_version or 0) + 1


def generate_prior_config(custom_profile_id: int, output_path: str) -> None:
    """
    Generate a YAML configuration template for profile priors.

    Args:
        custom_profile_id: ID of the custom profile
        output_path: Path where to save the generated YAML

    Raises:
        ValueError: If profile not found or has no parameters
        FileExistsError: If output file already exists
    """
    db = SessionLocal()

    try:
        # Fetch the custom profile
        profile = db.query(GraphHopperCustomProfile).filter(
            GraphHopperCustomProfile.id == custom_profile_id
        ).first()

        if not profile:
            raise ValueError(f"Custom profile with ID {custom_profile_id} not found")

        if not profile.parameters:
            raise ValueError(f"Profile '{profile.name}' (ID: {custom_profile_id}) has no parameters defined")

        # Get next version for this profile
        next_version = get_next_prior_version(db, custom_profile_id)

        # Build configuration
        config = {
            'custom_profile_id': custom_profile_id,
            'version': next_version,
            'parameters': {param: 1.0 for param in sorted(profile.parameters)},
            'training_metadata': {
                'routes_used': None,
                'convergence_metric': None,
                'notes': "Manually configured priors"
            }
        }

        # Check if output file already exists
        output_path_obj = Path(output_path)
        if output_path_obj.exists():
            raise FileExistsError(f"Output file already exists: {output_path}")

        # Create parent directory if needed
        output_path_obj.parent.mkdir(parents=True, exist_ok=True)

        # Write YAML with nice formatting
        with open(output_path_obj, 'w', encoding='utf-8') as f:
            f.write(f"# Prior configuration for GraphHopper Custom Profile\n")
            f.write(f"# Profile: {profile.name} (ID: {custom_profile_id})\n")
            f.write(f"# Description: {profile.description or 'No description'}\n")
            f.write(f"# Generated for version: {next_version}\n\n")

            yaml.dump(config, f, default_flow_style=False, sort_keys=False, indent=2)

        print(f"✅ Prior configuration template generated!")
        print(f"   Profile: {profile.name} (ID: {custom_profile_id})")
        print(f"   Parameters: {len(profile.parameters)} parameters")
        print(f"   Version: {next_version}")
        print(f"   Output: {output_path}")
        print(f"\n📝 Next steps:")
        print(f"   1. Edit {output_path} and set parameter values")
        print(f"   2. Insert priors: uv run ./scripts/add_prior_config.py --insert {output_path}")

    finally:
        db.close()


def validate_prior_config(config: Dict[str, Any]) -> None:
    """
    Validate the structure and content of a prior configuration.

    Args:
        config: Parsed YAML configuration

    Raises:
        ValueError: If configuration is invalid
    """
    # Check required top-level fields
    required_fields = ['custom_profile_id', 'version', 'parameters']
    missing_fields = [field for field in required_fields if field not in config]
    if missing_fields:
        raise ValueError(f"Missing required fields in configuration: {missing_fields}")

    # Validate types
    if not isinstance(config['custom_profile_id'], int):
        raise ValueError("custom_profile_id must be an integer")

    if not isinstance(config['version'], int) or config['version'] < 1:
        raise ValueError("version must be a positive integer")

    if not isinstance(config['parameters'], dict):
        raise ValueError("parameters must be a dictionary")

    if not config['parameters']:
        raise ValueError("parameters dictionary cannot be empty")

    # Validate parameter values
    for param_name, param_value in config['parameters'].items():
        if not isinstance(param_name, str) or not param_name.strip():
            raise ValueError("Parameter names must be non-empty strings")

        if not isinstance(param_value, (int, float)):
            raise ValueError(f"Parameter '{param_name}' must have a numeric value, got: {type(param_value)}")

        if param_value <= 0:
            raise ValueError(f"Parameter '{param_name}' must have a positive value, got: {param_value}")


def insert_prior_config(config_path: str) -> int:
    """
    Insert priors from a YAML configuration file.

    Args:
        config_path: Path to the YAML configuration file

    Returns:
        ID of the created ProfilePrior record

    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If configuration is invalid
        yaml.YAMLError: If YAML is malformed
    """
    config_path_obj = Path(config_path)
    if not config_path_obj.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    # Load and validate YAML
    try:
        with open(config_path_obj, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise yaml.YAMLError(f"Invalid YAML format in {config_path}: {e}")

    if not config:
        raise ValueError("Configuration file is empty or contains no data")

    # Validate configuration structure
    validate_prior_config(config)

    db = SessionLocal()

    try:
        # Validate custom profile exists
        profile = db.query(GraphHopperCustomProfile).filter(
            GraphHopperCustomProfile.id == config['custom_profile_id']
        ).first()

        if not profile:
            raise ValueError(f"Custom profile with ID {config['custom_profile_id']} not found")

        # Validate parameters match profile
        profile_params = set(profile.parameters) if profile.parameters else set()
        config_params = set(config['parameters'].keys())

        if profile_params != config_params:
            missing_params = profile_params - config_params
            extra_params = config_params - profile_params

            error_parts = []
            if missing_params:
                error_parts.append(f"Missing parameters: {sorted(missing_params)}")
            if extra_params:
                error_parts.append(f"Extra parameters: {sorted(extra_params)}")

            profile_info = f"Profile '{profile.name}' expects: {sorted(profile_params)}"
            raise ValueError(f"{'. '.join(error_parts)}. {profile_info}")

        # Check if this version already exists
        existing_prior = db.query(ProfilePrior).filter(
            ProfilePrior.profile_id == config['custom_profile_id'],
            ProfilePrior.version == config['version']
        ).first()

        if existing_prior:
            raise ValueError(
                f"Prior version {config['version']} already exists for profile {config['custom_profile_id']}. "
                f"Use a different version number or delete the existing prior first."
            )

        # Create the ProfilePrior record
        prior = ProfilePrior(
            profile_id=config['custom_profile_id'],
            parameters=config['parameters'],
            training_metadata=config.get('training_metadata', {}),
            version=config['version'],
            is_active=True  # New priors are active by default
        )

        db.add(prior)
        db.commit()

        print(f"✅ Prior configuration inserted successfully!")
        print(f"   Prior ID: {prior.id}")
        print(f"   Profile: {profile.name} (ID: {config['custom_profile_id']})")
        print(f"   Version: {config['version']}")
        print(f"   Parameters: {len(config['parameters'])}")

        # Show parameter summary
        print(f"   Parameter values:")
        for param_name in sorted(config['parameters'].keys()):
            param_value = config['parameters'][param_name]
            print(f"     {param_name}: {param_value}")

        return prior.id

    except IntegrityError as e:
        db.rollback()
        if "unique_profile_prior_version" in str(e):
            raise ValueError(
                f"Prior version {config['version']} already exists for profile {config['custom_profile_id']}")
        else:
            raise ValueError(f"Database constraint error: {e}")
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Generate and insert prior configurations for GraphHopper custom profiles",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Generate a configuration template
    uv run ./scripts/add_prior_config.py --create --custom_profile_id 1 -o ./prior_config.yaml

    # Insert priors from configuration
    uv run ./scripts/add_prior_config.py --insert ./prior_config.yaml
        """
    )

    # Create mutually exclusive group for create vs insert
    action_group = parser.add_mutually_exclusive_group(required=True)

    action_group.add_argument(
        "--create",
        action="store_true",
        help="Generate a prior configuration template"
    )

    action_group.add_argument(
        "--insert",
        metavar="CONFIG_FILE",
        help="Insert priors from YAML configuration file"
    )

    # Arguments for --create mode
    parser.add_argument(
        "--custom_profile_id",
        type=int,
        help="Custom profile ID (required with --create)"
    )

    parser.add_argument(
        "-o", "--output",
        help="Output path for generated configuration (required with --create)"
    )

    args = parser.parse_args()

    try:
        if args.create:
            # Validate required arguments for create mode
            if args.custom_profile_id is None:
                parser.error("--custom_profile_id is required with --create")
            if args.output is None:
                parser.error("-o/--output is required with --create")

            generate_prior_config(args.custom_profile_id, args.output)

        elif args.insert:
            insert_prior_config(args.insert)

    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()