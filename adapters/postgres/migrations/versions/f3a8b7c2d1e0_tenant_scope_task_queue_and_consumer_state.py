"""tenant scope task queue dedup and consumer state

Revision ID: f3a8b7c2d1e0
Revises: 81fe0505b506
Create Date: 2026-07-09 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f3a8b7c2d1e0"
down_revision: Union[str, Sequence[str], None] = "81fe0505b506"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    dialect = op.get_context().dialect.name

    # --- TaskQueue: make dedup unique constraint tenant-scoped ---
    if dialect == "sqlite":
        with op.batch_alter_table("sa_task_queue") as batch_op:
            batch_op.drop_constraint("uix_comment_video", type_="unique")
            batch_op.create_unique_constraint(
                "uix_owner_comment_video",
                ["owner_user_id", "comment_id", "video_id"],
            )
    else:
        op.drop_constraint("uix_comment_video", "sa_task_queue", type_="unique")
        op.create_unique_constraint(
            "uix_owner_comment_video",
            "sa_task_queue",
            ["owner_user_id", "comment_id", "video_id"],
        )

    # --- ConsumerState: add owner_user_id and enforce per-tenant uniqueness ---
    if dialect == "sqlite":
        with op.batch_alter_table("sa_consumer_state") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "owner_user_id",
                    sa.String(length=64),
                    nullable=False,
                    server_default="",
                )
            )
            batch_op.create_index(
                "ix_sa_consumer_state_owner_user_id",
                ["owner_user_id"],
                unique=False,
            )
            batch_op.create_unique_constraint(
                "uix_owner_consumer_state",
                ["owner_user_id", "consumer_id"],
            )
    else:
        op.add_column(
            "sa_consumer_state",
            sa.Column(
                "owner_user_id",
                sa.String(length=64),
                nullable=False,
                server_default="",
            ),
        )
        op.create_index(
            "ix_sa_consumer_state_owner_user_id",
            "sa_consumer_state",
            ["owner_user_id"],
            unique=False,
        )
        op.create_unique_constraint(
            "uix_owner_consumer_state",
            "sa_consumer_state",
            ["owner_user_id", "consumer_id"],
        )


def downgrade() -> None:
    """Downgrade schema."""
    dialect = op.get_context().dialect.name

    if dialect == "sqlite":
        with op.batch_alter_table("sa_consumer_state") as batch_op:
            batch_op.drop_constraint("uix_owner_consumer_state", type_="unique")
            batch_op.drop_index("ix_sa_consumer_state_owner_user_id")
            batch_op.drop_column("owner_user_id")

        with op.batch_alter_table("sa_task_queue") as batch_op:
            batch_op.drop_constraint("uix_owner_comment_video", type_="unique")
            batch_op.create_unique_constraint(
                "uix_comment_video", ["comment_id", "video_id"]
            )
    else:
        op.drop_constraint(
            "uix_owner_consumer_state", "sa_consumer_state", type_="unique"
        )
        op.drop_index(
            "ix_sa_consumer_state_owner_user_id", table_name="sa_consumer_state"
        )
        op.drop_column("sa_consumer_state", "owner_user_id")

        op.drop_constraint("uix_owner_comment_video", "sa_task_queue", type_="unique")
        op.create_unique_constraint(
            "uix_comment_video", "sa_task_queue", ["comment_id", "video_id"]
        )
