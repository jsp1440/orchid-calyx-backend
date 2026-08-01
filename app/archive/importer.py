from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic

from app.archive.checkpoint import CheckpointStore
from app.archive.control import ArchiveRunConflict, ArchiveRunControl
from app.archive.entities import EntityExtractor, NullEntityExtractor
from app.archive.extractor import DocumentExtractor
from app.archive.fingerprint import sha256_file
from app.archive.policy import ArchivePolicy
from app.archive.registry import ArchiveRegistry
from app.archive.relationships import NullRelationshipExtractor, RelationshipExtractor
from app.archive.scanner import ArchiveScanner, ScannedFile


@dataclass(frozen=True, slots=True)
class ImportOptions:
    checkpoint_interval: int = 100
    extract_zip: bool = True


class ArchiveImporter:
    def __init__(
        self,
        registry: ArchiveRegistry | None = None,
        scanner: ArchiveScanner | None = None,
        extractor: DocumentExtractor | None = None,
        entity_extractor: EntityExtractor | None = None,
        relationship_extractor: RelationshipExtractor | None = None,
        policy: ArchivePolicy | None = None,
        control: ArchiveRunControl | None = None,
    ) -> None:
        self.registry = registry or ArchiveRegistry()
        self.policy = policy or ArchivePolicy.from_environment()
        self.scanner = scanner or ArchiveScanner(self.policy)
        self.extractor = extractor or DocumentExtractor()
        self.entity_extractor = entity_extractor or NullEntityExtractor()
        self.relationship_extractor = relationship_extractor or NullRelationshipExtractor()
        self.checkpoints = CheckpointStore(self.registry)
        self.control = control or ArchiveRunControl(self.registry)

    def start(self, source: Path, options: ImportOptions | None = None) -> uuid.UUID:
        options = options or ImportOptions()
        authorized = self.policy.authorize_source(source)
        run_id = self.control.create_queued_run(str(authorized), asdict(options))
        self.execute(run_id)
        return run_id

    def execute(self, run_id: uuid.UUID) -> uuid.UUID:
        run = self.registry.run(run_id)
        if not run:
            raise KeyError(f"unknown archive import run: {run_id}")
        try:
            source = self.policy.authorize_source(Path(run["source_path"]))
            options = ImportOptions(**dict(run.get("options") or {}))
            checkpoint = self.checkpoints.load(run_id) or {"next_file_index": 0}
        except Exception as exc:
            self.control.fail_unclaimed(run_id, str(exc))
            raise

        attempt = self.control.claim(run_id)
        try:
            with self.control.lease_guard(run_id, attempt):
                self._run(
                    run_id,
                    source,
                    options,
                    attempt=attempt,
                    start_index=int(checkpoint["next_file_index"]),
                )
        except Exception:
            self.control.complete(run_id, "interrupted", attempt)
            raise
        return run_id

    def resume(self, run_id: uuid.UUID) -> uuid.UUID:
        return self.execute(run_id)

    def _discover(
        self, source: Path, options: ImportOptions, temp_root: Path
    ) -> list[ScannedFile]:
        if source.is_file() and source.suffix.lower() == ".zip" and options.extract_zip:
            extracted = self.scanner.extract_zip(source, temp_root / "extracted")
            return list(self.scanner.scan(extracted))
        return list(self.scanner.scan(source))

    def _cancel_if_requested(
        self,
        run_id: uuid.UUID,
        attempt: int,
        *,
        next_index: int,
        relative_path: str | None,
        started: float,
    ) -> bool:
        if not self.control.cancellation_requested(run_id):
            return False
        self.checkpoints.save(
            run_id,
            next_index=next_index,
            relative_path=relative_path,
            state={"cancelled": True, "elapsed_seconds": monotonic() - started},
        )
        self.control.complete(run_id, "cancelled", attempt)
        return True

    def _run(
        self,
        run_id: uuid.UUID,
        source: Path,
        options: ImportOptions,
        *,
        attempt: int,
        start_index: int,
    ) -> None:
        started = monotonic()
        if self._cancel_if_requested(
            run_id,
            attempt,
            next_index=start_index,
            relative_path=None,
            started=started,
        ):
            return

        with TemporaryDirectory(prefix="calyx-archive-") as temp:
            files = self._discover(source, options, Path(temp))
            if self._cancel_if_requested(
                run_id,
                attempt,
                next_index=start_index,
                relative_path=None,
                started=started,
            ):
                return
            if start_index == 0:
                self.registry.update_run_counters(run_id, files_discovered=len(files))
            for index, item in enumerate(files[start_index:], start=start_index):
                if not self.control.owns_claim(run_id, attempt):
                    raise ArchiveRunConflict("archive import lease ownership was lost")
                if self._cancel_if_requested(
                    run_id,
                    attempt,
                    next_index=index,
                    relative_path=item.relative_path,
                    started=started,
                ):
                    return
                try:
                    digest = sha256_file(item.path)
                    source_uri = item.path.resolve().as_uri()
                    if self.registry.find_file_by_sha256(digest):
                        self.registry.record_duplicate(
                            run_id,
                            relative_path=item.relative_path,
                            digest=digest,
                            source_uri=source_uri,
                        )
                        self.registry.update_run_counters(
                            run_id, duplicates_skipped=1, files_processed=1
                        )
                        continue
                    extracted = self.extractor.extract(item.path)
                    entities = self.entity_extractor.extract(extracted.text)
                    relationships = self.relationship_extractor.extract(
                        extracted.text, list(entities)
                    )
                    self.registry.register_document(
                        run_id=run_id,
                        relative_path=item.relative_path,
                        digest=digest,
                        size_bytes=item.size_bytes,
                        extraction_method=extracted.extraction_method,
                        text=extracted.text,
                        metadata={"structured_data": extracted.structured_data},
                        entities=entities,
                        relationships=relationships,
                        source_uri=source_uri,
                    )
                    self.registry.update_run_counters(
                        run_id,
                        files_processed=1,
                        documents_indexed=1,
                        entities_extracted=len(entities),
                        relationships_created=len(relationships),
                    )
                except Exception as exc:  # noqa: BLE001 - per-file isolation is required
                    self.registry.record_error(run_id, item.relative_path, str(exc))
                    self.registry.update_run_counters(run_id, files_processed=1)
                finally:
                    next_index = index + 1
                    if next_index % options.checkpoint_interval == 0:
                        self.checkpoints.save(
                            run_id,
                            next_index=next_index,
                            relative_path=item.relative_path,
                            state={"elapsed_seconds": monotonic() - started},
                        )
            self.checkpoints.save(
                run_id,
                next_index=len(files),
                relative_path=files[-1].relative_path if files else None,
                state={"complete": True, "elapsed_seconds": monotonic() - started},
            )
        self.control.complete(run_id, "completed", attempt)
