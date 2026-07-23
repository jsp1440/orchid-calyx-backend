"""Harvest orchestration for registered source plugins."""

from __future__ import annotations

from typing import Any, Mapping

from .models import HarvestCheckpoint, HarvestResult
from .registry import HarvesterRegistry, registry


class HarvestManager:
    """Runs one registered harvester until completion or a page limit."""

    def __init__(
        self,
        *,
        persistence: Any,
        checkpoints: Any,
        metrics: Any,
        plugin_registry: HarvesterRegistry = registry,
    ) -> None:
        self.persistence = persistence
        self.checkpoints = checkpoints
        self.metrics = metrics
        self.registry = plugin_registry

    def run(
        self,
        source: str,
        *,
        job_key: str = "default",
        max_pages: int | None = None,
        initial_state: Mapping[str, Any] | None = None,
    ) -> HarvestResult:
        harvester_cls = self.registry.get(source)
        harvester = harvester_cls(
            persistence=self.persistence,
            checkpoints=self.checkpoints,
            metrics=self.metrics,
        )
        harvester.authenticate()

        checkpoint = self.checkpoints.load(harvester.source, job_key)
        state: dict[str, Any] = dict(initial_state or {})
        if checkpoint is not None:
            state.update(checkpoint.state)
            state.update(
                cursor=checkpoint.cursor,
                offset=checkpoint.offset,
                processed=checkpoint.processed,
                completed=checkpoint.completed,
            )

        pages = fetched = normalized = persisted = rejected = 0
        completed = bool(state.get("completed", False))

        while not completed and (max_pages is None or pages < max_pages):
            page = harvester.fetch_page(state or None)
            pages += 1
            fetched += len(page.records)
            accepted_records: list[Mapping[str, Any]] = []

            for raw_record in page.records:
                try:
                    record = harvester.normalize(raw_record)
                except Exception:
                    rejected += 1
                    self.metrics.increment(harvester.source, "normalization_errors")
                    continue
                if harvester.validate(record):
                    accepted_records.append(record)
                    normalized += 1
                else:
                    rejected += 1

            if accepted_records:
                persisted += harvester.persist(accepted_records)

            state.update(page.next_checkpoint)
            state["processed"] = int(state.get("processed", 0)) + len(page.records)
            completed = bool(page.end_of_stream)
            state["completed"] = completed
            harvester.checkpoint(job_key, state)

            self.metrics.increment(harvester.source, "pages")
            self.metrics.increment(harvester.source, "fetched", len(page.records))
            self.metrics.increment(harvester.source, "normalized", len(accepted_records))
            self.metrics.increment(harvester.source, "persisted", len(accepted_records))
            self.metrics.increment(
                harvester.source,
                "rejected",
                len(page.records) - len(accepted_records),
            )

            if not page.records and not page.end_of_stream:
                raise RuntimeError(
                    f"{harvester.source} returned an empty non-terminal page"
                )

        final_checkpoint = self.checkpoints.load(harvester.source, job_key)
        if final_checkpoint is None:
            final_checkpoint = HarvestCheckpoint(
                source=harvester.source,
                job_key=job_key,
                completed=completed,
                state=state,
            )

        return HarvestResult(
            source=harvester.source,
            job_key=job_key,
            pages=pages,
            fetched=fetched,
            normalized=normalized,
            persisted=persisted,
            rejected=rejected,
            completed=completed,
            checkpoint=final_checkpoint,
        )
