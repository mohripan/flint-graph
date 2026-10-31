"""Voice model choice, cloned voices, license acceptance and line delivery (ADR 0045).

A character's voice names a catalog model plus a stock voice or a voice reference
(#176, #178). Jobs snapshot the model, the reference hash and its consent record and
the language. A creator's acceptance of a model license is recorded per workspace
with the license hash (#178). Per-line delivery overrides are editor metadata
(#177). Existing Kokoro profiles and jobs keep their meaning: the model defaults to
Kokoro-82M and the language to English.

Revision ID: 0032_narrative_voice_models
Revises: 0031_narrative_voice_references
"""

import sqlalchemy as sa
from alembic import op

revision = "0032_narrative_voice_models"
down_revision = "0031_narrative_voice_references"
branch_labels = None
depends_on = None

REFERENCE = ["id", "project_id", "tenant_id"]
ONE_VOICE = (
    "(voice IS NOT NULL AND reference_id IS NULL AND reference_sha256 IS NULL "
    "AND consent IS NULL) OR (voice IS NULL AND reference_id IS NOT NULL "
    "AND reference_sha256 IS NOT NULL AND consent IS NOT NULL)"
)
DELIVERIES = (
    "emotion IN ('neutral','happy','angry','sad','afraid','surprised','whisper','shout',"
    "'dramatic','tender') AND intensity BETWEEN 0 AND 1"
)


def upgrade() -> None:
    op.add_column("narrative_character_profiles", sa.Column("voice_model", sa.String(64)))
    op.add_column("narrative_character_profiles", sa.Column("voice_reference_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_narrative_character_profile_reference",
        "narrative_character_profiles",
        "narrative_voice_references",
        ["voice_reference_id", "project_id", "tenant_id"],
        REFERENCE,
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_narrative_character_profile_one_voice",
        "narrative_character_profiles",
        "voice IS NULL OR voice_reference_id IS NULL",
    )
    op.add_column(
        "narrative_voice_jobs",
        sa.Column("voice_model", sa.String(64), nullable=False, server_default="kokoro-82m"),
    )
    op.add_column("narrative_voice_jobs", sa.Column("reference_id", sa.Uuid()))
    op.add_column("narrative_voice_jobs", sa.Column("reference_sha256", sa.String(64)))
    op.add_column("narrative_voice_jobs", sa.Column("consent", sa.JSON()))
    op.add_column(
        "narrative_voice_jobs",
        sa.Column("language", sa.String(8), nullable=False, server_default="en"),
    )
    op.alter_column("narrative_voice_jobs", "voice", existing_type=sa.String(32), nullable=True)
    op.create_foreign_key(
        "fk_narrative_voice_job_reference",
        "narrative_voice_jobs",
        "narrative_voice_references",
        ["reference_id", "project_id", "tenant_id"],
        REFERENCE,
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_narrative_voice_job_one_voice",
        "narrative_voice_jobs",
        ONE_VOICE,
    )
    op.create_table(
        "narrative_voice_license_acceptances",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("model_id", sa.String(64), nullable=False),
        sa.Column("license_id", sa.String(64), nullable=False),
        sa.Column("license_sha256", sa.String(64), nullable=False),
        sa.Column(
            "accepted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_narrative_voice_license_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_narrative_voice_license_user",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "user_id",
            "model_id",
            "license_sha256",
            name="uq_narrative_voice_license_acceptance",
        ),
    )
    op.create_table(
        "narrative_line_deliveries",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.String(64), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("emotion", sa.String(16), nullable=False),
        sa.Column("intensity", sa.Float(), nullable=False),
        sa.Column("tag", sa.String(16), nullable=True),
        sa.Column("updated_by_user_id", sa.Uuid(), nullable=False),
        *(
            sa.Column(
                name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
            )
            for name in ("created_at", "updated_at")
        ),
        sa.PrimaryKeyConstraint("project_id", "node_id"),
        sa.ForeignKeyConstraint(
            ["project_id", "tenant_id"],
            ["narrative_projects.id", "narrative_projects.tenant_id"],
            name="fk_narrative_line_delivery_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            name="fk_narrative_line_delivery_user",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(DELIVERIES, name="ck_narrative_line_delivery_value"),
    )


def downgrade() -> None:
    if not op.get_context().as_sql:
        cloned = op.get_bind().scalar(
            sa.text("SELECT count(*) FROM narrative_voice_jobs WHERE reference_id IS NOT NULL")
        )
        if cloned:
            raise RuntimeError("Cloned-voice jobs exist; 0031 cannot represent them.")
    op.drop_table("narrative_line_deliveries")
    op.drop_table("narrative_voice_license_acceptances")
    op.drop_constraint("ck_narrative_voice_job_one_voice", "narrative_voice_jobs", type_="check")
    op.drop_constraint(
        "fk_narrative_voice_job_reference", "narrative_voice_jobs", type_="foreignkey"
    )
    op.alter_column("narrative_voice_jobs", "voice", existing_type=sa.String(32), nullable=False)
    for name in ("language", "consent", "reference_sha256", "reference_id", "voice_model"):
        op.drop_column("narrative_voice_jobs", name)
    op.drop_constraint(
        "ck_narrative_character_profile_one_voice", "narrative_character_profiles", type_="check"
    )
    op.drop_constraint(
        "fk_narrative_character_profile_reference",
        "narrative_character_profiles",
        type_="foreignkey",
    )
    op.drop_column("narrative_character_profiles", "voice_reference_id")
    op.drop_column("narrative_character_profiles", "voice_model")
