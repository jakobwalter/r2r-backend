#!/usr/bin/env python3
"""
Add a new GraphHopper custom profile to the database.

Usage:
    uv run ./scripts/add_custom_profile.py \
        --discipline "road" \
        --name "road_01" \
        --description "Basic road profile" \
        --template_path ./data/templates/road_01.json
"""

import argparse
import json
import re
import hashlib
import sys
from pathlib import Path
from typing import List, Set

# Add the parent directory to the Python path to import from r2r_backend
sys.path.insert(0, str(Path(__file__).parent.parent))

from r2r_backend.db.base import SessionLocal, engine
from r2r_backend.db.models import Base, GraphHopperCustomProfile, DisciplineType
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func


def extract_parameters_from_template(template_content: str) -> List[str]:
    """
    Extract parameter placeholders from GraphHopper template JSON.

    Finds all instances of {parameter_name} in the template.
    Uses improved regex from existing codebase.

    Args:
        template_content: The JSON template as a string

    Returns:
        Sorted list of unique parameter names
    """
    # Use the better regex pattern from operations.py
    # Matches {parameter_name} where parameter_name starts with letter and contains letters, numbers, underscores
    pattern = r'\{([a-z][a-z0-9_]*)\}'
    matches = re.findall(pattern, template_content)

    # Convert to set to remove duplicates, then back to sorted list
    unique_parameters = set(matches)

    # Warn about duplicates (like in operations.py)
    if len(matches) != len(unique_parameters):
        duplicates = [p for p in unique_parameters if matches.count(p) > 1]
        print(f"Info: Found duplicate parameters in template: {duplicates}")

    return sorted(list(unique_parameters))


def compute_template_hash(template_content: str) -> str:
    """
    Compute SHA256 hash of template content for change detection.

    Args:
        template_content: The JSON template as a string

    Returns:
        Hexadecimal SHA256 hash string
    """
    return hashlib.sha256(template_content.encode('utf-8')).hexdigest()


def validate_template_json(template_path: Path) -> str:
    """
    Load and validate the GraphHopper template JSON.

    Args:
        template_path: Path to the JSON template file

    Returns:
        Template content as string

    Raises:
        FileNotFoundError: If template file doesn't exist
        json.JSONDecodeError: If template is not valid JSON
    """
    if not template_path.exists():
        raise FileNotFoundError(f"Template file not found: {template_path}")

    try:
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Validate it's proper JSON
        json.loads(content)

        return content
    except json.JSONDecodeError as e:
        raise json.JSONDecodeError(f"Invalid JSON in template file: {e}")


def validate_discipline(discipline: str) -> DisciplineType:
    """
    Validate and convert discipline string to enum.

    Args:
        discipline: Discipline name as string

    Returns:
        DisciplineType enum value

    Raises:
        ValueError: If discipline is not valid
    """
    try:
        return DisciplineType(discipline.lower())
    except ValueError:
        valid_disciplines = [d.value for d in DisciplineType]
        raise ValueError(f"Invalid discipline '{discipline}'. Valid options: {valid_disciplines}")


def get_next_version(db_session, discipline: DisciplineType) -> int:
    """
    Get the next version number for a discipline.

    Args:
        db_session: SQLAlchemy session
        discipline: The discipline type

    Returns:
        Next version number (1 if no existing profiles)
    """
    max_version = db_session.query(
        func.max(GraphHopperCustomProfile.version)
    ).filter(
        GraphHopperCustomProfile.discipline == discipline
    ).scalar()

    return (max_version or 0) + 1


def create_custom_profile(
        discipline: str,
        name: str,
        description: str,
        template_path: str
) -> int:
    """
    Create a new GraphHopper custom profile.

    Args:
        discipline: Bike discipline (road, gravel, mtb, etc.)
        name: Profile name
        description: Profile description
        template_path: Path to GraphHopper JSON template

    Returns:
        ID of created profile

    Raises:
        Various exceptions for validation errors
    """
    # Validate inputs
    discipline_enum = validate_discipline(discipline)
    template_path_obj = Path(template_path)
    template_content = validate_template_json(template_path_obj)

    # Extract parameters and compute hash
    parameters = extract_parameters_from_template(template_content)
    template_hash = compute_template_hash(template_content)

    print(f"📋 Found {len(parameters)} parameters in template: {parameters}")

    # Parse template as JSON for validation, then convert back to dict for storage
    try:
        template_json = json.loads(template_content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in template: {e}")

    # Validate required GraphHopper fields
    if "priority" not in template_json:
        raise ValueError("GraphHopper template must contain 'priority' field")
    if not isinstance(template_json["priority"], list):
        raise ValueError("GraphHopper 'priority' field must be an array")

    # Create database session
    db = SessionLocal()

    try:
        # Get next version for this discipline
        version = get_next_version(db, discipline_enum)

        # Create the profile
        profile = GraphHopperCustomProfile(
            discipline=discipline_enum,
            name=name,
            description=description,
            template=template_json,
            parameters=parameters,
            version=version,
            is_active=True,
            template_hash=template_hash
        )

        db.add(profile)
        db.commit()

        print(f"✅ Profile created successfully!")
        print(f"   ID: {profile.id}")
        print(f"   Discipline: {discipline_enum.value}")
        print(f"   Name: {name}")
        print(f"   Version: {version}")
        print(f"   Parameters: {len(parameters)}")
        print(f"   Template hash: {template_hash[:12]}...")

        return profile.id

    except IntegrityError as e:
        db.rollback()
        if "unique_discipline_version" in str(e):
            raise ValueError(f"A profile for discipline '{discipline}' version {version} already exists")
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
        description="Add a new GraphHopper custom profile to the database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example:
    uv run ./scripts/add_custom_profile.py \\
        --discipline "road" \\
        --name "road_01" \\
        --description "Basic road profile optimized for paved surfaces" \\
        --template_path ./data/templates/road_01.json
        """
    )

    parser.add_argument(
        "--discipline",
        required=True,
        help=f"Bike discipline ({', '.join([d.value for d in DisciplineType])})"
    )

    parser.add_argument(
        "--name",
        required=True,
        help="Profile name (e.g., 'road_01', 'gravel_scenic')"
    )

    parser.add_argument(
        "--description",
        required=True,
        help="Profile description"
    )

    parser.add_argument(
        "--template_path",
        required=True,
        help="Path to GraphHopper JSON template file"
    )

    args = parser.parse_args()

    try:
        profile_id = create_custom_profile(
            discipline=args.discipline,
            name=args.name,
            description=args.description,
            template_path=args.template_path
        )

        print(f"\n🎯 Next steps:")
        print(f"   1. Generate prior config:")
        print(
            f"      uv run ./scripts/add_prior_config.py --create --custom_profile_id {profile_id} -o ./prior_config.yaml")
        print(f"   2. Edit the prior_config.yaml file with parameter values")
        print(f"   3. Insert priors:")
        print(f"      uv run ./scripts/add_prior_config.py --insert ./prior_config.yaml")

    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()