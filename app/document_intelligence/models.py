from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

class DocumentClass(StrEnum):
    PRIMARY_RESEARCH="PRIMARY_RESEARCH"; REVIEW_SYNTHESIS="REVIEW_SYNTHESIS"; TAXONOMIC_WORK="TAXONOMIC_WORK"
    BOOK_OR_CHAPTER="BOOK_OR_CHAPTER"; CONSERVATION_ASSESSMENT="CONSERVATION_ASSESSMENT"; TECHNICAL_REPORT="TECHNICAL_REPORT"
    EDUCATIONAL_MATERIAL="EDUCATIONAL_MATERIAL"; AI_RESEARCH_SYNTHESIS="AI_RESEARCH_SYNTHESIS"; INTELLIGENCE_REPORT="INTELLIGENCE_REPORT"
    INTERNAL_ORGANIZATIONAL="INTERNAL_ORGANIZATIONAL"; DATASET_OR_SUPPLEMENT="DATASET_OR_SUPPLEMENT"; OTHER="OTHER"

@dataclass(frozen=True)
class Anchor:
    page_start:int|None=None; page_end:int|None=None; char_start:int|None=None; char_end:int|None=None; region:dict[str,Any]|None=None; block_id:str|None=None; logical_unit:int|None=None; ocr_derived:bool=False; confidence:float|None=None
@dataclass(frozen=True)
class Block:
    kind:str; text:str; sequence:int; anchor:Anchor; heading_level:int|None=None; metadata:dict[str,Any]=field(default_factory=dict)
@dataclass(frozen=True)
class IntermediateDocument:
    units:tuple[dict[str,Any],...]; blocks:tuple[Block,...]; tables:tuple[dict[str,Any],...]=(); media:tuple[dict[str,Any],...]=(); warnings:tuple[str,...]=(); extraction_method:str="VERBATIM"; source_revision_id:int|None=None; adapter_name:str|None=None; adapter_version:str|None=None; languages:tuple[str,...]=()
@dataclass(frozen=True)
class Classification:
    document_class:DocumentClass; subclass:str|None; confidence:float; method:str; version:str; evidence:tuple[str,...]
