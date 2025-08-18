"""add means and variances to profile priors

Revision ID: 246677e8a89f
Revises: f44c8b1fa365
Create Date: 2025-08-18 09:46:36.059241

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '246677e8a89f'
down_revision: Union[str, Sequence[str], None] = 'f44c8b1fa365'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    """Add means and variances columns, migrate data, drop old parameters column."""

    # Step 1: Add new columns
    print("Adding means and variances columns...")
    op.add_column('profile_priors',
                  sa.Column('means', postgresql.JSONB(), nullable=True))
    op.add_column('profile_priors',
                  sa.Column('variances', postgresql.JSONB(), nullable=True))

    # Step 2: Migrate existing data
    print("Migrating existing data from parameters to means...")

    # Get database connection
    connection = op.get_bind()

    # Update existing records: copy parameters to means, set default variances
    connection.execute(text("""
                            UPDATE profile_priors
                            SET means     = parameters,
                                variances = (SELECT jsonb_object_agg(key, 0.01)
                                             FROM jsonb_each(parameters))
                            WHERE parameters IS NOT NULL
                            """))

    # Step 3: Make new columns non-nullable now that data is migrated
    print("Making new columns non-nullable...")
    op.alter_column('profile_priors', 'means', nullable=False)
    op.alter_column('profile_priors', 'variances', nullable=False)

    # Step 4: Drop old parameters column
    print("Dropping old parameters column...")
    op.drop_column('profile_priors', 'parameters')

def downgrade():
    """Restore parameters column and migrate data back."""

    # Step 1: Add back parameters column
    print("Restoring parameters column...")
    op.add_column('profile_priors',
                  sa.Column('parameters', postgresql.JSONB(), nullable=True))

    # Step 2: Migrate data back from means to parameters
    print("Migrating data from means back to parameters...")
    connection = op.get_bind()

    connection.execute(text("""
                            UPDATE profile_priors
                            SET parameters = means
                            WHERE means IS NOT NULL
                            """))

    # Step 3: Make parameters column non-nullable
    op.alter_column('profile_priors', 'parameters', nullable=False)

    # Step 4: Drop new columns
    print("Dropping means and variances columns...")
    op.drop_column('profile_priors', 'variances')
    op.drop_column('profile_priors', 'means')
