"""A local index of what this machine has registered. It never leaves.

The chain holds a pixel hash and nothing else, which is correct and useless
for a photographer: given `0x2224a686…` there is no way to know it was
`IMG_0230.CR3` in last April's shoot. That mapping has to live somewhere, and
the only safe somewhere is here.

**Why not on chain, and why not in a resolver record.** A description is
unbounded personal data -- a caption naming a client, a location, a person --
and anything published is permanent and unretractable. It also adds nothing a
verifier could check: the chain already proves the registration, and a caption
proves nothing about the pixels. So the network gets the hash, and the disk
gets the meaning (`docs/security.md`).

The file path is the sharper case. It says where a RAW lives on this machine,
and a RAW is a forgery kit (`docs/adversarial.md`), so a path is a map to one.
It is recorded because a photographer needs it and it is never returned to
anything but localhost.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path

#: Beside the fingerprints, and gitignored for the same reason they are.
CATALOGUE = Path(os.environ.get("GENESIS_CATALOGUE", "data/catalogue.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS images (
    image_hash      TEXT PRIMARY KEY,
    perceptual_hash TEXT,
    body_id         TEXT,
    body_name       TEXT,
    pce             REAL,
    registered_at   INTEGER,
    tx_hash         TEXT,
    block_number    INTEGER,
    session_id      TEXT,
    file_name       TEXT,
    file_path       TEXT,
    description     TEXT DEFAULT '',
    noted_at        INTEGER
);
CREATE INDEX IF NOT EXISTS images_session ON images(session_id);
CREATE INDEX IF NOT EXISTS images_body ON images(body_id);
"""


def _connect() -> sqlite3.Connection:
    CATALOGUE.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(CATALOGUE)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    return connection


def record_image(**fields) -> None:
    """Insert or update one registration. Idempotent on `image_hash`.

    Re-registering the same pixels is impossible on chain, so a second write
    here means the operator registered the same photograph from a different
    path -- worth keeping the newer path rather than the older.
    """
    columns = [
        "image_hash", "perceptual_hash", "body_id", "body_name", "pce",
        "registered_at", "tx_hash", "block_number", "session_id",
        "file_name", "file_path", "description", "noted_at",
    ]
    values = {column: fields.get(column) for column in columns}
    with closing(_connect()) as connection, connection:
        connection.execute(
            f"""INSERT INTO images ({','.join(columns)})
                VALUES ({','.join('?' for _ in columns)})
                ON CONFLICT(image_hash) DO UPDATE SET
                  file_name=excluded.file_name,
                  file_path=excluded.file_path,
                  tx_hash=COALESCE(excluded.tx_hash, images.tx_hash),
                  session_id=COALESCE(excluded.session_id, images.session_id)""",
            [values[c] for c in columns],
        )


def describe(image_hash: str, description: str) -> bool:
    """Attach or replace a caption. Returns False if the hash is unknown."""
    import time

    with closing(_connect()) as connection, connection:
        cursor = connection.execute(
            "UPDATE images SET description = ?, noted_at = ? WHERE image_hash = ?",
            (description, int(time.time()), image_hash),
        )
        return cursor.rowcount > 0


def listing(limit: int = 500) -> list[dict]:
    with closing(_connect()) as connection:
        rows = connection.execute(
            "SELECT * FROM images ORDER BY registered_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(row) for row in rows]


def statistics() -> dict:
    """What the operator actually wants to know: how much is indexed, and how
    well it scored. Not an analytics surface -- it never leaves the machine."""
    with closing(_connect()) as connection:
        row = connection.execute(
            """SELECT COUNT(*) AS images,
                      COUNT(DISTINCT session_id) AS sessions,
                      COUNT(DISTINCT body_id) AS bodies,
                      MIN(pce) AS weakest, MAX(pce) AS strongest, AVG(pce) AS mean,
                      SUM(CASE WHEN description <> '' THEN 1 ELSE 0 END) AS described,
                      MIN(registered_at) AS first_seen, MAX(registered_at) AS last_seen
               FROM images"""
        ).fetchone()
        per_body = connection.execute(
            """SELECT body_name, COUNT(*) AS images FROM images
               GROUP BY body_name ORDER BY images DESC"""
        ).fetchall()

    stats = {k: row[k] for k in row.keys()}
    stats["perBody"] = [dict(r) for r in per_body]
    stats["catalogue"] = str(CATALOGUE)
    return stats
