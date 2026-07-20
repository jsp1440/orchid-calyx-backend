from dataclasses import dataclass,field
from typing import Any
MODES={"LEXICAL","SEMANTIC","HYBRID"}; EXPANSIONS={"NONE","PARENT_METADATA","COMPLETE_SECTION","COMPLETE_PROTOCOL","COMPLETE_RESULT_PACKAGE","COMPLETE_TAXONOMIC_TREATMENT","COMPLETE_IDENTIFICATION_KEY","AUTO"}
@dataclass(frozen=True)
class RetrievalQuery:
 text:str; mode:str="HYBRID"; collections:tuple[str,...]=(); object_types:tuple[str,...]=(); document_classes:tuple[str,...]=(); authors:tuple[str,...]=(); language:str|None=None; verification_state:str|None=None; review_state:str|None=None; temporal_status:str|None=None; intended_consumers:tuple[str,...]=(); active_only:bool=True; historical:bool=False; limit:int=10; per_source_limit:int=2; offset:int=0; parent_expansion:str="AUTO"; internal_access:bool=False; filters:dict[str,Any]=field(default_factory=dict)
 def __post_init__(self):
  normalized=" ".join(self.text.split())
  if not normalized or len(normalized)>500: raise ValueError("INVALID_QUERY_LENGTH")
  if self.mode not in MODES or self.parent_expansion not in EXPANSIONS: raise ValueError("UNSUPPORTED_QUERY_COMBINATION")
  if not 1<=self.limit<=100 or not 1<=self.per_source_limit<=20 or not 0<=self.offset<=10000: raise ValueError("INVALID_RETRIEVAL_LIMIT")
  object.__setattr__(self,"text",normalized)
