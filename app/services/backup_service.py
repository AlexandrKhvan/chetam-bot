from __future__ import annotations

import asyncio
import gzip
import logging
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.config import Settings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class BackupResult:
    local_path: Path
    size_bytes: int
    s3_uri: str = ""


class BackupService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def run_backup(self, *, keep_local: int = 14) -> BackupResult:
        return await asyncio.to_thread(self._run_backup_sync, keep_local)

    def _run_backup_sync(self, keep_local: int) -> BackupResult:
        db_path = Path(self.settings.database_path)
        if not db_path.exists():
            raise FileNotFoundError(f"Database file not found: {db_path}")

        backup_dir = Path(self.settings.local_backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        tmp_sqlite = backup_dir / f"chetam-{stamp}.db"
        gz_path = backup_dir / f"chetam-{stamp}.db.gz"

        # Safe online SQLite backup (WAL-consistent)
        src = sqlite3.connect(str(db_path))
        dst = sqlite3.connect(str(tmp_sqlite))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()

        with tmp_sqlite.open("rb") as f_in, gzip.open(gz_path, "wb", compresslevel=6) as f_out:
            shutil.copyfileobj(f_in, f_out)
        tmp_sqlite.unlink(missing_ok=True)

        # Rotate old local backups
        existing = sorted(backup_dir.glob("chetam-*.db.gz"), reverse=True)
        for old_file in existing[keep_local:]:
            old_file.unlink(missing_ok=True)

        size_bytes = gz_path.stat().st_size
        s3_uri = ""

        bucket = self.settings.s3_backup_bucket.strip()
        if bucket:
            import boto3

            prefix = self.settings.s3_backup_prefix.strip("/")
            key = f"{prefix}/{gz_path.name}" if prefix else gz_path.name
            s3 = boto3.client("s3", region_name=self.settings.aws_region)
            s3.upload_file(
                str(gz_path),
                bucket,
                key,
                ExtraArgs={"ContentType": "application/gzip"},
            )
            s3_uri = f"s3://{bucket}/{key}"
            logger.info("Uploaded SQLite backup to %s (%d bytes)", s3_uri, size_bytes)
        else:
            logger.info("Created local SQLite backup %s (%d bytes)", gz_path, size_bytes)

        return BackupResult(local_path=gz_path, size_bytes=size_bytes, s3_uri=s3_uri)
