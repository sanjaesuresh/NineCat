"""league sync standings and roster slot upsert key

Revision ID: 65cb464f1186
Revises: 914838585199
Create Date: 2026-08-11 17:54:14.683588

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '65cb464f1186'
down_revision: Union[str, Sequence[str], None] = '914838585199'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('standings',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('league_id', sa.BigInteger(), nullable=False),
    sa.Column('team_id', sa.BigInteger(), nullable=False),
    sa.Column('rank', sa.Integer(), nullable=False),
    sa.Column('wins', sa.Integer(), nullable=False),
    sa.Column('losses', sa.Integer(), nullable=False),
    sa.Column('ties', sa.Integer(), nullable=False),
    sa.Column('synced_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['league_id'], ['leagues.id'], name=op.f('fk_standings_league_id_leagues'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['team_id'], ['teams.id'], name=op.f('fk_standings_team_id_teams'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_standings')),
    sa.UniqueConstraint('league_id', 'team_id', name=op.f('uq_standings_league_id'))
    )
    op.create_index(op.f('ix_standings_league_id'), 'standings', ['league_id'], unique=False)
    op.create_index(op.f('ix_standings_team_id'), 'standings', ['team_id'], unique=False)
    # sync's idempotency key for the roster full-replace upsert (ledger-noted gap
    # from task 3); enforced at the db level even though delete-then-insert makes
    # duplicates impossible in the normal sync flow
    op.create_unique_constraint(
        op.f('uq_roster_slots_team_id'), 'roster_slots', ['team_id', 'yahoo_player_key']
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f('uq_roster_slots_team_id'), 'roster_slots', type_='unique')
    op.drop_index(op.f('ix_standings_team_id'), table_name='standings')
    op.drop_index(op.f('ix_standings_league_id'), table_name='standings')
    op.drop_table('standings')
