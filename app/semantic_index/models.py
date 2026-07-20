from dataclasses import dataclass,field
from enum import StrEnum
from typing import Any
class Eligibility(StrEnum):
 ELIGIBLE="ELIGIBLE"; EXCLUDED_BY_POLICY="EXCLUDED_BY_POLICY"; EXCLUDED_EMPTY="EXCLUDED_EMPTY"; EXCLUDED_UNSUPPORTED_LANGUAGE="EXCLUDED_UNSUPPORTED_LANGUAGE"; EXCLUDED_UNVERIFIED="EXCLUDED_UNVERIFIED"; EXCLUDED_REVIEW_REQUIRED="EXCLUDED_REVIEW_REQUIRED"; EXCLUDED_SUPERSEDED="EXCLUDED_SUPERSEDED"; DEFERRED="DEFERRED"; FAILED_VALIDATION="FAILED_VALIDATION"
class PlanAction(StrEnum):
 NEW="NEW"; CHANGED_TEXT="CHANGED_TEXT"; CHANGED_METADATA="CHANGED_METADATA"; UNCHANGED="UNCHANGED"; MODEL_CHANGED="MODEL_CHANGED"; CONFIGURATION_CHANGED="CONFIGURATION_CHANGED"; COLLECTION_CHANGED="COLLECTION_CHANGED"; POLICY_EXCLUDED="POLICY_EXCLUDED"; REVIEW_REQUIRED="REVIEW_REQUIRED"; SUPERSEDED="SUPERSEDED"; TOMBSTONE_REQUIRED="TOMBSTONE_REQUIRED"; FAILED_VALIDATION="FAILED_VALIDATION"
@dataclass(frozen=True)
class IndexDocument:
 source_object_type:str; source_object_id:int; revision_id:int; extraction_run_id:int; text:str; representation_type:str="VERBATIM"; parent_type:str|None=None; parent_id:int|None=None; collections:tuple[str,...]=("GENERAL_BRAIN",); title:str|None=None; source_anchor_ids:tuple[int,...]=(); document_class:str="OTHER"; language:str="en"; intended_consumers:tuple[str,...]=(); temporal_status:str="UNKNOWN"; verification_state:str="UNVERIFIED"; review_state:str="CLEAR"; internal_indexing_permission:bool=False; display_policy:str="UNKNOWN_REQUIRES_REVIEW"; metadata:dict[str,Any]=field(default_factory=dict)
