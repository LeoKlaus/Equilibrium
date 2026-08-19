"""Fix swapped foreign keys on link tables

scenedevicelink, commandmacrolink, scenemacrolink, and devicemacrolink all
had their two ID columns' foreign_key targets swapped (e.g.
scenedevicelink.scene_id pointed at device.id and device_id pointed at
scene.id). SQLAlchemy resolved relationships correctly regardless, by FK
target rather than column name, so existing data is internally consistent
but stored under the swapped understanding: the column named scene_id
currently holds device ids, and vice versa.

This migration rebuilds each table (rename/create/copy/drop) with the
corrected FK constraints, swapping the two ID columns as part of the copy
step (INSERT ... SELECT with the source columns reordered) rather than via
a separate in-place UPDATE. An in-place `UPDATE t SET a = b, b = a` was
tried first and is unsafe here: since (a, b) is a composite primary key,
SQLite applies the UPDATE row by row against the live unique constraint,
and two "cross-linked" rows (e.g. (scene=10, device=20) and
(scene=20, device=10) both existing) can collide mid-update even though
the final result would have been valid - confirmed by reproducing it
against adversarial synthetic data. Swapping during the copy into a fresh,
initially-empty table avoids this entirely: batch_alter_table's
recreate='always' was also tried and confirmed (against a synthetic
pre-fix database, run through a real alembic upgrade) to just reflect and
rewrite the existing table unchanged rather than syncing to the corrected
model, hence the explicit rebuild.

Revision ID: 6ed74759fd50
Revises: 14c4f04c9ba6
Create Date: 2026-08-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '6ed74759fd50'
down_revision: Union[str, Sequence[str], None] = '14c4f04c9ba6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _rebuild_and_swap(name: str, create_sql: str, insert_columns: list[str], select_columns: list[str]) -> None:
    """Rebuild `name` with `create_sql`, copying rows from the old table
    into the new one with the source columns reordered per
    `select_columns` - this is what performs the swap, in the same step as
    the copy, so the live table is never left holding a transient
    duplicate of its own primary key.
    """
    op.execute(f"ALTER TABLE {name} RENAME TO {name}_old")
    op.execute(create_sql)
    insert_list = ", ".join(insert_columns)
    select_list = ", ".join(select_columns)
    op.execute(f"INSERT INTO {name} ({insert_list}) SELECT {select_list} FROM {name}_old")
    op.execute(f"DROP TABLE {name}_old")


def upgrade() -> None:
    """Upgrade schema."""
    _rebuild_and_swap(
        "scenedevicelink",
        "CREATE TABLE scenedevicelink ("
        "scene_id INTEGER NOT NULL REFERENCES scene(id), "
        "device_id INTEGER NOT NULL REFERENCES device(id), "
        "PRIMARY KEY (scene_id, device_id))",
        insert_columns=["scene_id", "device_id"],
        select_columns=["device_id", "scene_id"],
    )
    _rebuild_and_swap(
        "commandmacrolink",
        "CREATE TABLE commandmacrolink ("
        "command_id INTEGER NOT NULL REFERENCES command(id), "
        "macro_id INTEGER NOT NULL REFERENCES macro(id), "
        "PRIMARY KEY (command_id, macro_id))",
        insert_columns=["command_id", "macro_id"],
        select_columns=["macro_id", "command_id"],
    )
    _rebuild_and_swap(
        "scenemacrolink",
        "CREATE TABLE scenemacrolink ("
        "scene_id INTEGER NOT NULL REFERENCES scene(id), "
        "macro_id INTEGER NOT NULL REFERENCES macro(id), "
        "PRIMARY KEY (scene_id, macro_id))",
        insert_columns=["scene_id", "macro_id"],
        select_columns=["macro_id", "scene_id"],
    )
    _rebuild_and_swap(
        "devicemacrolink",
        "CREATE TABLE devicemacrolink ("
        "device_id INTEGER NOT NULL REFERENCES device(id), "
        "macro_id INTEGER NOT NULL REFERENCES macro(id), "
        "PRIMARY KEY (device_id, macro_id))",
        insert_columns=["device_id", "macro_id"],
        select_columns=["macro_id", "device_id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    _rebuild_and_swap(
        "scenedevicelink",
        "CREATE TABLE scenedevicelink ("
        "scene_id INTEGER NOT NULL REFERENCES device(id), "
        "device_id INTEGER NOT NULL REFERENCES scene(id), "
        "PRIMARY KEY (scene_id, device_id))",
        insert_columns=["scene_id", "device_id"],
        select_columns=["device_id", "scene_id"],
    )
    _rebuild_and_swap(
        "commandmacrolink",
        "CREATE TABLE commandmacrolink ("
        "command_id INTEGER NOT NULL REFERENCES macro(id), "
        "macro_id INTEGER NOT NULL REFERENCES command(id), "
        "PRIMARY KEY (command_id, macro_id))",
        insert_columns=["command_id", "macro_id"],
        select_columns=["macro_id", "command_id"],
    )
    _rebuild_and_swap(
        "scenemacrolink",
        "CREATE TABLE scenemacrolink ("
        "scene_id INTEGER NOT NULL REFERENCES macro(id), "
        "macro_id INTEGER NOT NULL REFERENCES scene(id), "
        "PRIMARY KEY (scene_id, macro_id))",
        insert_columns=["scene_id", "macro_id"],
        select_columns=["macro_id", "scene_id"],
    )
    _rebuild_and_swap(
        "devicemacrolink",
        "CREATE TABLE devicemacrolink ("
        "device_id INTEGER NOT NULL REFERENCES macro(id), "
        "macro_id INTEGER NOT NULL REFERENCES device(id), "
        "PRIMARY KEY (device_id, macro_id))",
        insert_columns=["device_id", "macro_id"],
        select_columns=["macro_id", "device_id"],
    )
