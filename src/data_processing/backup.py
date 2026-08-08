"""Database backup and restore functionality.

Supports exporting the database to JSON and restoring from backups.
"""

import json
import logging
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from src.config import DATA_DIR, OUTPUT_DIR

logger = logging.getLogger(__name__)

# Tables to include in backup
BACKUP_TABLES = [
    "films",
    "reviews",
    "ai_reviews",
    "ratings",
    "watchlist",
    "diary",
    "liked_films",
    "rate_limits",
    "schema_version",
]


def get_table_schema(cursor: sqlite3.Cursor, table_name: str) -> list[dict]:
    """Get column information for a table.

    Args:
        cursor: Database cursor
        table_name: Name of the table

    Returns:
        List of column info dicts
    """
    cursor.execute(f"PRAGMA table_info({table_name})")  # noqa: S608
    columns = []
    for row in cursor.fetchall():
        columns.append(
            {
                "cid": row[0],
                "name": row[1],
                "type": row[2],
                "notnull": row[3],
                "default": row[4],
                "pk": row[5],
            }
        )
    return columns


def export_database(
    db_path: Path | None = None,
    output_path: Path | None = None,
    include_rate_limits: bool = False,
) -> Path:
    """Export database to JSON file.

    Args:
        db_path: Path to database file. Defaults to DATA_DIR / "movie_database.db"
        output_path: Path for output JSON. Defaults to OUTPUT_DIR / "backup_TIMESTAMP.json"
        include_rate_limits: Whether to include rate limit history

    Returns:
        Path to the created backup file
    """
    db_path = db_path or (DATA_DIR / "movie_database.db")
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_path or (OUTPUT_DIR / f"backup_{timestamp}.json")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    backup_data: dict[str, Any] = {
        "metadata": {
            "version": "1.0",
            "created_at": datetime.now().isoformat(),
            "source_db": str(db_path),
        },
        "tables": {},
    }

    tables_to_backup = BACKUP_TABLES.copy()
    if not include_rate_limits:
        tables_to_backup = [t for t in tables_to_backup if t != "rate_limits"]

    for table_name in tables_to_backup:
        try:
            # Get schema
            schema = get_table_schema(cursor, table_name)

            # Get data
            cursor.execute(f"SELECT * FROM {table_name}")  # noqa: S608
            rows = [dict(row) for row in cursor.fetchall()]

            backup_data["tables"][table_name] = {
                "schema": schema,
                "row_count": len(rows),
                "data": rows,
            }
            logger.info(f"Exported {len(rows)} rows from {table_name}")

        except sqlite3.OperationalError as e:
            logger.warning(f"Could not export table {table_name}: {e}")

    conn.close()

    # Write to JSON
    OUTPUT_DIR.mkdir(exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(backup_data, f, indent=2, ensure_ascii=False, default=str)

    logger.info(f"Database exported to {output_path}")
    return output_path


def restore_database(
    backup_path: Path,
    db_path: Path | None = None,
    merge: bool = False,
    create_backup: bool = True,
) -> dict:
    """Restore database from JSON backup.

    Args:
        backup_path: Path to backup JSON file
        db_path: Path to target database. Defaults to DATA_DIR / "movie_database.db"
        merge: If True, merge with existing data. If False, replace.
        create_backup: Create backup of existing database before restore

    Returns:
        Dict with restore statistics
    """
    db_path = db_path or (DATA_DIR / "movie_database.db")

    if not backup_path.exists():
        raise FileNotFoundError(f"Backup file not found: {backup_path}")

    # Load backup
    with open(backup_path, encoding="utf-8") as f:
        backup_data = json.load(f)

    stats = {"tables_restored": 0, "rows_restored": 0, "rows_merged": 0}

    # Backup existing database if it exists
    if db_path.exists() and create_backup:
        backup_existing = db_path.with_suffix(".db.bak")
        shutil.copy(db_path, backup_existing)
        logger.info(f"Created backup of existing database: {backup_existing}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        for table_name, table_data in backup_data.get("tables", {}).items():
            if table_name not in BACKUP_TABLES:
                logger.warning(f"Skipping unknown table: {table_name}")
                continue

            rows = table_data.get("data", [])
            if not rows:
                continue

            # Validate column names against the live schema before they
            # reach the SQL string. Stacked statements cannot execute, but
            # an unrecognized name otherwise fails every row insert while
            # the restore still reports the table as restored.
            valid_columns = {col["name"] for col in get_table_schema(cursor, table_name)}
            columns = [col for col in rows[0].keys() if col in valid_columns]
            rejected = [col for col in rows[0].keys() if col not in valid_columns]
            if rejected:
                logger.warning(f"{table_name}: ignoring unknown columns {rejected}")
            if not columns:
                logger.error(f"{table_name}: no recognized columns, skipping table")
                stats["tables_skipped"] = stats.get("tables_skipped", 0) + 1
                continue
            placeholders = ", ".join(["?" for _ in columns])
            column_names = ", ".join(columns)

            if merge:
                # Use INSERT OR REPLACE for merge
                sql = (
                    f"INSERT OR REPLACE INTO {table_name} ({column_names}) VALUES ({placeholders})"  # noqa: S608
                )
            else:
                # Clear table first for full restore
                cursor.execute(f"DELETE FROM {table_name}")  # noqa: S608
                sql = f"INSERT INTO {table_name} ({column_names}) VALUES ({placeholders})"  # noqa: S608

            # Insert rows
            for row in rows:
                values = [row.get(col) for col in columns]
                try:
                    cursor.execute(sql, values)
                    if merge:
                        stats["rows_merged"] += 1
                    else:
                        stats["rows_restored"] += 1
                except sqlite3.Error as e:
                    logger.warning(f"Error inserting row into {table_name}: {e}")

            stats["tables_restored"] += 1
            logger.info(f"Restored {len(rows)} rows to {table_name}")

        conn.commit()
        logger.info(f"Database restore complete: {stats}")

    except Exception as e:
        conn.rollback()
        logger.error(f"Restore failed: {e}")
        raise
    finally:
        conn.close()

    return stats


def list_backups(backup_dir: Path | None = None) -> list[dict]:
    """List available backup files.

    Args:
        backup_dir: Directory to search. Defaults to OUTPUT_DIR.

    Returns:
        List of backup info dicts sorted by date (newest first)
    """
    backup_dir = backup_dir or OUTPUT_DIR

    if not backup_dir.exists():
        return []

    backups = []
    for path in backup_dir.glob("backup_*.json"):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)

            metadata = data.get("metadata", {})
            tables = data.get("tables", {})
            total_rows = sum(t.get("row_count", 0) for t in tables.values())

            backups.append(
                {
                    "path": path,
                    "filename": path.name,
                    "created_at": metadata.get("created_at", "Unknown"),
                    "size_bytes": path.stat().st_size,
                    "table_count": len(tables),
                    "total_rows": total_rows,
                }
            )
        except Exception as e:
            logger.warning(f"Could not read backup {path}: {e}")

    # Sort by creation date, newest first
    backups.sort(key=lambda x: x["created_at"], reverse=True)
    return backups


def main() -> None:
    """CLI for backup/restore operations."""
    import argparse

    parser = argparse.ArgumentParser(description="Database backup and restore")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Export command
    export_parser = subparsers.add_parser("export", help="Export database to JSON")
    export_parser.add_argument("-o", "--output", type=Path, help="Output file path")
    export_parser.add_argument(
        "--include-rate-limits",
        action="store_true",
        help="Include rate limit history in backup",
    )

    # Restore command
    restore_parser = subparsers.add_parser("restore", help="Restore database from JSON")
    restore_parser.add_argument("backup_file", type=Path, help="Backup file to restore")
    restore_parser.add_argument(
        "--merge",
        action="store_true",
        help="Merge with existing data instead of replacing",
    )
    restore_parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Don't create backup of existing database",
    )

    # List command
    subparsers.add_parser("list", help="List available backups")

    args = parser.parse_args()

    if args.command == "export":
        output = export_database(
            output_path=args.output,
            include_rate_limits=args.include_rate_limits,
        )
        print(f"\nDatabase exported to: {output}")

    elif args.command == "restore":
        stats = restore_database(
            backup_path=args.backup_file,
            merge=args.merge,
            create_backup=not args.no_backup,
        )
        print("\nRestore complete:")
        print(f"  Tables restored: {stats['tables_restored']}")
        print(f"  Rows restored: {stats['rows_restored']}")
        if args.merge:
            print(f"  Rows merged: {stats['rows_merged']}")

    elif args.command == "list":
        backups = list_backups()
        if not backups:
            print("\nNo backups found in output/ directory")
        else:
            print(f"\nFound {len(backups)} backup(s):\n")
            for b in backups:
                size_kb = b["size_bytes"] / 1024
                print(f"  {b['filename']}")
                print(f"    Created: {b['created_at']}")
                print(f"    Size: {size_kb:.1f} KB")
                print(f"    Tables: {b['table_count']}, Rows: {b['total_rows']}")
                print()

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
