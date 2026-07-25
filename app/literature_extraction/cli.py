from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Sequence

from .context import PipelineContext
from .extractors.metadata import MetadataExtractor
from .extractors.sections import SectionExtractor
from .ingest import build_empty_paper, ingest_text
from .output import write_output_bundle
from .pipeline import PipelineRunner


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="orchid-extract",
        description="Run the Orchid Continuum literature extraction pipeline.",
    )
    parser.add_argument("source", type=Path, help="UTF-8 text document to ingest")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        required=True,
        help="Directory where extraction artifacts will be written",
    )
    return parser


async def run_cli(source: Path, output_dir: Path) -> int:
    document = ingest_text(source)
    context = PipelineContext(source_path=source, output_dir=output_dir)
    paper = build_empty_paper(
        document,
        pipeline_version=context.config.pipeline_version,
    )
    result = await PipelineRunner(
        [MetadataExtractor(), SectionExtractor()]
    ).run(context, paper)
    write_output_bundle(result, document, output_dir)
    return 0 if result.analysis_manifest.status == "completed" else 1


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return asyncio.run(run_cli(args.source, args.output))


if __name__ == "__main__":
    raise SystemExit(main())
