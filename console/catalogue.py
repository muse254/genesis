"""Local index mapping registered hashes to files and captions. It never leaves this machine.

Captions are personal data and add nothing verifiable, so never on chain
(`docs/security.md`). File paths locate RAWs, which are forgery kits
(`docs/adversarial.md`): never return them to anything but localhost.
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
    """Insert or update one registration. Idempotent on `image_hash`; a repeat keeps the newer path."""
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


def sync(bodies: dict[str, str], images: list[dict], indexed_block: int) -> None:
    """Make this machine's rows for `bodies` (id -> name) match the subgraph's `images`.

    Chain wins on its fields; names and captions stay local. Rows the chain lacks
    are deleted unless newer than `indexed_block` (not indexed yet).
    """
    on_chain = {i["imageHash"].lower() for i in images}
    with closing(_connect()) as connection, connection:
        for image in images:
            body_id = image["body"]["id"].lower()
            connection.execute(
                """INSERT INTO images (image_hash, perceptual_hash, body_id, body_name,
                                       pce, registered_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(image_hash) DO UPDATE SET
                     perceptual_hash=excluded.perceptual_hash, body_id=excluded.body_id,
                     body_name=excluded.body_name, pce=excluded.pce,
                     registered_at=excluded.registered_at""",
                (image["imageHash"].lower(), image["perceptualHash"].lower(), body_id,
                 bodies.get(body_id), float(image["pceScore"]), int(image["registeredAt"])),
            )
        for body_id in bodies:
            for row in connection.execute(
                "SELECT image_hash, block_number FROM images WHERE lower(body_id) = ?",
                (body_id,),
            ).fetchall():
                stale = row["block_number"] is None or row["block_number"] <= indexed_block
                if row["image_hash"].lower() not in on_chain and stale:
                    connection.execute("DELETE FROM images WHERE image_hash = ?",
                                       (row["image_hash"],))


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
    """How much is indexed and how well it scored. Local only."""
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


def clear() -> int:
    """Empty the archive (after a chain `resetAll`, every row would be a false claim); return rows removed."""
    with closing(_connect()) as connection:
        removed = connection.execute("SELECT COUNT(*) FROM images").fetchone()[0]
        connection.execute("DELETE FROM images")
        connection.commit()
    return int(removed)
