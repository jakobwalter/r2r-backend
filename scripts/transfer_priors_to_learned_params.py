#!/usr/bin/env python3
"""
Transfer prior means to learned_parameters table for specific user profiles.

This script creates toy data by:
1. Creating user profiles if they don't exist
2. Transferring specific prior means to learned_parameters table

Usage:
    uv run ./scripts/transfer_priors_to_learned_params.py \\
        --user_id "123e4567-e89b-12d3-a456-426614174000" \\
        --prior_id 1

    # Transfer multiple priors for the same user
    uv run ./scripts/transfer_priors_to_learned_params.py \\
        --user_id "123e4567-e89b-12d3-a456-426614174000" \\
        --prior_id 1 \\
        --prior_id 2
"""

import argparse
import sys
import uuid
from pathlib import Path
from typing import List

# Add the parent directory to the Python path to import from r2r_backend
sys.path.insert(0, str(Path(__file__).parent.parent))

from r2r_backend.db.base import SessionLocal
from r2r_backend.db.models import (
    GraphHopperCustomProfile,
    ProfilePrior,
    UserProfile,
    LearnedParameters
)
from sqlalchemy.exc import IntegrityError


def validate_uuid(uuid_string: str) -> str:
    """
    Validate that a string is a valid UUID.

    Args:
        uuid_string: String to validate

    Returns:
        The validated UUID string

    Raises:
        ValueError: If the string is not a valid UUID
    """
    try:
        # This will raise ValueError if not a valid UUID
        uuid.UUID(uuid_string)
        return uuid_string
    except ValueError:
        raise ValueError(f"Invalid UUID format: {uuid_string}")


def get_or_create_user_profile(db_session, user_id: str, profile_id: int) -> UserProfile:
    """
    Get existing user profile or create a new one.

    Args:
        db_session: SQLAlchemy session
        user_id: UUID string of the user
        profile_id: ID of the custom profile

    Returns:
        UserProfile instance (existing or newly created)

    Raises:
        ValueError: If custom profile doesn't exist
    """
    # First check if custom profile exists
    custom_profile = db_session.query(GraphHopperCustomProfile).filter(
        GraphHopperCustomProfile.id == profile_id
    ).first()

    if not custom_profile:
        raise ValueError(f"Custom profile with ID {profile_id} not found")

    # Check if user profile already exists
    user_profile = db_session.query(UserProfile).filter(
        UserProfile.user_id == user_id,
        UserProfile.profile_id == profile_id
    ).first()

    if user_profile:
        print(f"   Using existing user profile (ID: {user_profile.id})")
        return user_profile

    # Create new user profile
    user_profile = UserProfile(
        user_id=user_id,
        profile_id=profile_id,
        custom_name=f"Profile for {custom_profile.name}",
        total_ratings=0
    )

    db_session.add(user_profile)
    db_session.flush()  # Get the ID without committing

    print(f"   Created new user profile (ID: {user_profile.id})")
    return user_profile


def transfer_prior_to_learned_params(
        user_id: str,
        prior_ids: List[int]
) -> List[str]:
    """
    Transfer specific priors to learned_parameters for a user.

    Args:
        user_id: UUID string of the user
        prior_ids: List of ProfilePrior IDs to transfer

    Returns:
        List of created LearnedParameters IDs

    Raises:
        ValueError: If validation fails
    """
    # Validate user_id format
    validate_uuid(user_id)

    if not prior_ids:
        raise ValueError("At least one prior_id must be specified")

    db = SessionLocal()
    created_learned_params = []

    try:
        for prior_id in prior_ids:
            print(f"\\n🔄 Processing prior ID {prior_id}...")

            # Fetch the prior
            prior = db.query(ProfilePrior).filter(
                ProfilePrior.id == prior_id
            ).first()

            if not prior:
                print(f"   ❌ Prior with ID {prior_id} not found, skipping")
                continue

            # Get or create user profile
            user_profile = get_or_create_user_profile(
                db, user_id, prior.profile_id
            )

            # Check if this user already has learned parameters marked as prior
            existing_learned_prior = db.query(LearnedParameters).filter(
                LearnedParameters.user_profile_id == user_profile.id,
                LearnedParameters.is_prior == True
            ).first()

            if existing_learned_prior:
                print(f"   ⚠️  User profile already has prior learned parameters (ID: {existing_learned_prior.id})")
                print(f"      Skipping to avoid duplicates")
                continue

            # Create learned parameters from prior means
            learned_params = LearnedParameters(
                user_profile_id=user_profile.id,
                parameters=prior.means,  # Transfer the means
                is_prior=True,
                rating_count_at_generation=0,
                convergence_metrics={
                    "source": "profile_prior",
                    "prior_id": prior_id,
                    "prior_version": prior.version,
                    "transferred_at": "auto_transfer"
                }
            )

            db.add(learned_params)
            db.flush()  # Get the ID

            created_learned_params.append(str(learned_params.id))

            print(f"   ✅ Created learned parameters (ID: {learned_params.id})")
            print(f"      Parameters: {list(prior.means.keys())}")
            print(f"      Values: {prior.means}")

        # Commit all changes
        db.commit()

        print(f"\\n🎉 Successfully transferred {len(created_learned_params)} priors to learned parameters")
        return created_learned_params

    except IntegrityError as e:
        db.rollback()
        if "unique_user_profile" in str(e):
            raise ValueError("User profile constraint violation - this shouldn't happen!")
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
        description="Transfer prior means to learned_parameters table for specific user profiles",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Transfer single prior
    uv run ./scripts/transfer_priors_to_learned_params.py \\
        --user_id "123e4567-e89b-12d3-a456-426614174000" \\
        --prior_id 1

    # Transfer multiple priors for same user
    uv run ./scripts/transfer_priors_to_learned_params.py \\
        --user_id "123e4567-e89b-12d3-a456-426614174000" \\
        --prior_id 1 \\
        --prior_id 2
        """
    )

    parser.add_argument(
        "--user_id",
        required=True,
        help="UUID of the user (will be used for both auth user and user profiles)"
    )

    parser.add_argument(
        "--prior_id",
        type=int,
        action="append",
        required=True,
        help="ID of the ProfilePrior to transfer (can be specified multiple times)"
    )

    args = parser.parse_args()

    try:
        print(f"🚀 Starting prior transfer for user: {args.user_id}")
        print(f"   Prior IDs to transfer: {args.prior_id}")

        created_ids = transfer_prior_to_learned_params(
            user_id=args.user_id,
            prior_ids=args.prior_id
        )

        if created_ids:
            print(f"\\n📋 Summary:")
            print(f"   User ID: {args.user_id}")
            print(f"   Created learned parameter IDs: {created_ids}")
            print(f"\\n🎯 Next steps:")
            print(f"   - Use these learned parameters in your frontend")
            print(f"   - Add segment ratings to trigger parameter updates")
            print(f"   - Test the routing with personalized parameters")
        else:
            print(f"\\n⚠️  No learned parameters were created (all were skipped)")

    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()