import csv
import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter()

DATA_DIR = Path(__file__).resolve().parent / "data"
CSV_PATH = DATA_DIR / "ipc_bns_mapping.csv"
DB_PATH = DATA_DIR / "mapping.db"


def initialize_database() -> None:
    """Create or refresh the SQLite mapping database from the canonical CSV."""
    needs_refresh = (
        not DB_PATH.exists()
        or DB_PATH.stat().st_mtime < CSV_PATH.stat().st_mtime
    )
    if not needs_refresh:
        return

    with sqlite3.connect(DB_PATH) as connection:
        connection.execute("DROP TABLE IF EXISTS ipc_bns_mapping")
        connection.execute(
            """
            CREATE TABLE ipc_bns_mapping (
                ipc_section TEXT NOT NULL,
                bns_section TEXT NOT NULL,
                section_title TEXT NOT NULL,
                notes TEXT NOT NULL
            )
            """
        )
        with CSV_PATH.open(newline="", encoding="utf-8") as csv_file:
            rows = csv.DictReader(csv_file)
            connection.executemany(
                """
                INSERT INTO ipc_bns_mapping
                    (ipc_section, bns_section, section_title, notes)
                VALUES
                    (:ipc_section, :bns_section, :section_title, :notes)
                """,
                rows,
            )


def _find_by(column: str, section: str):
    initialize_database()
    with sqlite3.connect(DB_PATH) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            f"""
            SELECT ipc_section, bns_section, section_title AS title, notes
            FROM ipc_bns_mapping
            WHERE {column} = ?
            """,
            (section,),
        ).fetchone()
    return dict(row) if row else None


def find_by_ipc(section: str):
    return _find_by("ipc_section", section)


def find_by_bns(section: str):
    return _find_by("bns_section", section)


@router.get("/mapping/ipc/{section}")
def get_bns_for_ipc(section: str):
    result = find_by_ipc(section)
    if not result:
        raise HTTPException(status_code=404, detail=f"No mapping found for IPC {section}")
    return result


@router.get("/mapping/bns/{section}")
def get_ipc_for_bns(section: str):
    result = find_by_bns(section)
    if not result:
        raise HTTPException(status_code=404, detail=f"No mapping found for BNS {section}")
    return result
