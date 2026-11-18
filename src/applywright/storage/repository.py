import re
import sqlite3
import os
from typing import Any, List, Optional, Sequence
from datetime import datetime, timezone
from enum import Enum
from applywright import lifecycle
from applywright.models import Job


class UpdateMode(str, Enum):
    DEFAULT = "default"
    ENRICHMENT = "enrichment"


class JobRepository:
    def __init__(self, db_path: str, read_only: bool = False):
        self.db_path = db_path
        self.read_only = read_only
        if not read_only:
            # Ensure directory exists
            os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
            self._init_db()

    def _get_connection(self):
        if self.read_only:
            conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        else:
            conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
        with open(schema_path, "r") as f:
            schema = f.read()
        with self._get_connection() as conn:
            conn.executescript(schema)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
            if "apply_url" not in columns:
                conn.execute("ALTER TABLE jobs ADD COLUMN apply_url TEXT")
            conn.commit()

    def find_cross_source_duplicates(self, job: Job) -> List[str]:
        """Return job_ids of jobs from other sources with the same normalized
        company and title."""

        def norm(text: Optional[str]) -> str:
            return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()

        target = (norm(job.company), norm(job.title))
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT job_id, company, title FROM jobs WHERE source != ?",
                (job.source,),
            ).fetchall()
        return [
            row["job_id"]
            for row in rows
            if (norm(row["company"]), norm(row["title"])) == target
        ]

    def upsert_job(
        self, job: Job, update_mode: UpdateMode = UpdateMode.DEFAULT
    ) -> tuple[bool, bool]:
        """
        Upsert a job into the database.
        Returns a tuple (created: bool, updated: bool).
        Only updates if data actually changed, and does NOT overwrite decision or notes.
        In "enrichment" mode, strictly preserves application lifecycle fields and handles blanks safely.
        """
        if not isinstance(update_mode, UpdateMode):
            raise ValueError(f"Invalid update_mode: {update_mode}")

        with self._get_connection() as conn:
            cursor = conn.cursor()

            existing = None
            if update_mode == UpdateMode.ENRICHMENT:
                if not job.external_id:
                    raise ValueError("external_id is required for enrichment mode")
                cursor.execute(
                    "SELECT * FROM jobs WHERE source = ? AND external_id = ?",
                    (job.source, job.external_id),
                )
                existing = cursor.fetchone()
            else:
                if job.external_id:
                    cursor.execute(
                        "SELECT * FROM jobs WHERE source = ? AND external_id = ?",
                        (job.source, job.external_id),
                    )
                    existing = cursor.fetchone()

                if not existing:
                    # Fallback to dedupe_key only in default mode
                    cursor.execute(
                        "SELECT * FROM jobs WHERE dedupe_key = ?", (job.dedupe_key,)
                    )
                    existing = cursor.fetchone()

            if not existing:
                if update_mode == UpdateMode.ENRICHMENT:
                    raise ValueError(
                        "Cannot enrich a non-existent job or job without matching source+external_id"
                    )
                # Insert new job
                cursor.execute(
                    """
                    INSERT INTO jobs (
                        job_id, external_id, dedupe_key, title, company, location,
                        remote_status, salary, employment_type, job_url, description, apply_url,
                        date_found, date_applied, application_status, source,
                        decision, notes, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        job.job_id,
                        job.external_id,
                        job.dedupe_key,
                        job.title,
                        job.company,
                        job.location,
                        job.remote_status,
                        job.salary,
                        job.employment_type,
                        job.job_url,
                        job.description,
                        job.apply_url,
                        job.date_found.isoformat() if job.date_found else None,
                        job.date_applied.isoformat() if job.date_applied else None,
                        job.application_status,
                        job.source,
                        job.decision,
                        job.notes,
                        job.created_at.isoformat(),
                        job.updated_at.isoformat(),
                    ),
                )
                return (True, False)
            else:
                updated = False
                fields_to_update = {}

                # Determine fields that are allowed to be updated based on mode
                allowed_fields = [
                    "title",
                    "company",
                    "location",
                    "remote_status",
                    "salary",
                    "employment_type",
                    "job_url",
                    "description",
                    "apply_url",
                    "external_id",
                    "source",
                    "date_found",
                ]

                if update_mode == UpdateMode.ENRICHMENT:
                    # strictly preserve application_status, date_applied, external_id, source etc in enrichment
                    allowed_fields = [
                        "title",
                        "company",
                        "location",
                        "remote_status",
                        "salary",
                        "employment_type",
                        "job_url",
                        "description",
                        "date_found",
                    ]

                for field in allowed_fields:
                    new_val = getattr(job, field)
                    if isinstance(new_val, datetime):
                        new_val = new_val.isoformat()
                    elif hasattr(new_val, "value"):
                        new_val = new_val.value

                    old_val = existing[field]

                    if new_val != old_val:
                        # Check for nonblank preservation
                        is_new_blank = new_val is None or (
                            isinstance(new_val, str) and not new_val.strip()
                        )
                        is_old_blank = old_val is None or (
                            isinstance(old_val, str) and not old_val.strip()
                        )

                        if is_new_blank and not is_old_blank:
                            continue  # skip overwriting a nonblank value with a blank one

                        fields_to_update[field] = new_val

                if update_mode == UpdateMode.DEFAULT:
                    fields_to_update.update(
                        lifecycle.merge_import_status(Job(**dict(existing)), job)
                    )

                if fields_to_update:
                    fields_to_update["updated_at"] = datetime.now(
                        timezone.utc
                    ).isoformat()
                    set_clause = ", ".join(
                        [f"{k} = ?" for k in fields_to_update.keys()]
                    )
                    values = list(fields_to_update.values())
                    values.append(existing["job_id"])

                    cursor.execute(
                        f"UPDATE jobs SET {set_clause} WHERE job_id = ?",  # nosec B608
                        values,
                    )
                    updated = True

                return (False, updated)

    def get_job(self, job_id: str) -> Optional[Job]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
            row = cursor.fetchone()
            if row:
                return Job(**dict(row))
            return None

    def list_jobs(
        self,
        status: Optional[str] = None,
        decision: Optional[str] = None,
        source: Optional[str] = None,
        date_from: Optional[str] = None,
        keywords: Optional[str] = None,
        limit: int = 50,
    ) -> List[Job]:
        with self._get_connection() as conn:
            cursor = conn.cursor()

            query = "SELECT * FROM jobs WHERE 1=1"
            params: List[Any] = []

            if status:
                query += " AND application_status = ?"
                params.append(status)
            if decision:
                query += " AND decision = ?"
                params.append(decision)
            if source:
                query += " AND source = ?"
                params.append(source)
            if date_from:
                query += " AND date_found >= ?"
                params.append(date_from)
            if keywords:
                # Basic LIKE search on title, company, description
                kw = f"%{keywords}%"
                query += " AND (title LIKE ? OR company LIKE ? OR description LIKE ?)"
                params.extend([kw, kw, kw])

            query += " ORDER BY date_found DESC, created_at DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [Job(**dict(row)) for row in rows]

    def list_jobs_for_triage(self, statuses: Sequence[str]) -> List[dict[str, Any]]:
        """Return the columns that triage reads, for jobs in the given statuses."""
        if not statuses:
            return []
        marks = ",".join("?" for _ in statuses)
        with self._get_connection() as conn:
            rows = conn.execute(
                f"""
                SELECT job_id, external_id, title, company, location, salary,
                       description, decision, source, application_status
                FROM jobs
                WHERE application_status IN ({marks})
                ORDER BY created_at
                """,  # nosec B608
                tuple(statuses),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_job_status(
        self,
        job_id: str,
        decision: Optional[str],
        notes: Optional[str] = None,
        submitted_at: Optional[datetime] = None,
        submission: Optional[lifecycle.Submission] = None,
    ) -> Optional[Job]:
        parsed = lifecycle.parse_decision(decision) if decision is not None else None

        conn = self._get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if row is None:
                conn.rollback()
                return None
            changes = lifecycle.decide(
                Job(**dict(row)), parsed, notes, submitted_at, submission
            )
            changes["updated_at"] = datetime.now(timezone.utc).isoformat()
            set_clause = ", ".join(f"{k} = ?" for k in changes)
            conn.execute(
                f"UPDATE jobs SET {set_clause} WHERE job_id = ?",  # nosec B608
                [*changes.values(), job_id],
            )
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

        return self.get_job(job_id)

    def select_jobs_for_deletion(
        self,
        job_ids: Optional[List[str]] = None,
        application_status: Optional[str] = None,
        decision: Optional[str] = None,
    ) -> tuple[List[Job], List[Job]]:
        """Resolve a deletion target set without deleting anything.

        Returns (deletable, protected). A job is protected -- never returned as
        deletable -- when it has been applied to, so submission history cannot be
        destroyed. Selection is by explicit job_ids and/or an application_status
        or decision filter; at least one selector is required.
        """
        if not job_ids and application_status is None and decision is None:
            raise ValueError(
                "Refusing to select every job: pass job_ids, application_status, "
                "or decision."
            )

        clauses: List[str] = []
        params: List[Any] = []
        if job_ids:
            clauses.append(f"job_id IN ({','.join('?' for _ in job_ids)})")
            params.extend(job_ids)
        if application_status is not None:
            clauses.append("application_status = ?")
            params.append(application_status)
        if decision is not None:
            clauses.append("decision = ?")
            params.append(decision)

        where = " AND ".join(clauses)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"SELECT * FROM jobs WHERE {where}", params)  # nosec B608
            jobs = [Job(**dict(row)) for row in cursor.fetchall()]

        deletable: List[Job] = []
        protected: List[Job] = []
        for job in jobs:
            (protected if lifecycle.is_protected(job) else deletable).append(job)
        return deletable, protected

    def delete_jobs(self, job_ids: List[str]) -> int:
        """Permanently delete the given jobs. Returns the number removed.

        This is a hard delete. A submitted job is never deleted, even when the
        caller names it. Callers gate this behind explicit confirmation.
        """
        if not job_ids:
            return 0
        marks = ",".join("?" for _ in job_ids)
        conn = self._get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                f"SELECT * FROM jobs WHERE job_id IN ({marks})",  # nosec B608
                job_ids,
            ).fetchall()
            removable = [
                row["job_id"]
                for row in rows
                if not lifecycle.is_protected(Job(**dict(row)))
            ]
            if not removable:
                conn.rollback()
                return 0
            cursor = conn.execute(
                f"DELETE FROM jobs WHERE job_id IN ({','.join('?' for _ in removable)})",  # nosec B608
                removable,
            )
            conn.commit()
            return cursor.rowcount
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
