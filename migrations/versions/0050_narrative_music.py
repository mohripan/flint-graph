"""Music and sound effects in the asset library (ADR 0066).

Revision ID: 0050_narrative_music
Revises: 0049_workspace_names_per_person
"""

from alembic import op

revision = "0050_narrative_music"
down_revision = "0049_workspace_names_per_person"
branch_labels = None
depends_on = None

OLD_KINDS = "kind IN ('character_portrait','background','sprite','image','font','voice')"
OLD_MEDIA = "media_type IN ('image/png','font/ttf','font/otf','audio/wav')"
OLD_SHAPE = (
    "size_bytes > 0 AND ((media_type = 'image/png' AND width > 0 AND height > 0 "
    "AND duration_ms IS NULL) OR (media_type = 'audio/wav' AND width IS NULL "
    "AND height IS NULL AND duration_ms > 0) OR (media_type IN ('font/ttf','font/otf') "
    "AND width IS NULL AND height IS NULL AND duration_ms IS NULL))"
)
KINDS = (
    "kind IN ('character_portrait','background','sprite','image','font','voice',"
    "'music','sound')"
)
MEDIA = "media_type IN ('image/png','font/ttf','font/otf','audio/wav','audio/ogg')"
SHAPE = (
    "size_bytes > 0 AND ((media_type = 'image/png' AND width > 0 AND height > 0 "
    "AND duration_ms IS NULL) OR (media_type IN ('audio/wav','audio/ogg') AND width IS NULL "
    "AND height IS NULL AND duration_ms > 0) OR (media_type IN ('font/ttf','font/otf') "
    "AND width IS NULL AND height IS NULL AND duration_ms IS NULL))"
)
NAMES = ("ck_narrative_asset_kind", "ck_narrative_asset_media_type", "ck_narrative_asset_shape")


def _replace(kinds: str, media: str, shape: str) -> None:
    for name in NAMES:
        op.drop_constraint(name, "narrative_assets", type_="check")
    op.create_check_constraint(NAMES[0], "narrative_assets", kinds)
    op.create_check_constraint(NAMES[1], "narrative_assets", media)
    op.create_check_constraint(NAMES[2], "narrative_assets", shape)


def upgrade() -> None:
    _replace(KINDS, MEDIA, SHAPE)


def downgrade() -> None:
    # Fails while music or sound files exist: removing them is the owner's decision.
    _replace(OLD_KINDS, OLD_MEDIA, OLD_SHAPE)
