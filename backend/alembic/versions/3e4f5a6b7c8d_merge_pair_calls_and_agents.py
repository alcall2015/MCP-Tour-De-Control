"""merge the SIM pair calls chain with the agents chain

Revision ID: 3e4f5a6b7c8d
Revises: 1c2d3e4f5a6b, 0b1c2d3e4f5a

The pairing retention column was added on both legs (e5f6a7b8c9d0 and
0b1c2d3e4f5a); both migrations skip the add when the column exists, so a
database that followed either leg upgrades cleanly through this merge.
"""

revision = "3e4f5a6b7c8d"
down_revision = ("1c2d3e4f5a6b", "0b1c2d3e4f5a")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
