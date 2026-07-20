from __future__ import annotations
import hashlib,math
from abc import ABC,abstractmethod
class ProviderError(RuntimeError):
 def __init__(self,message,retryable=False): super().__init__(message); self.retryable=retryable
class EmbeddingProvider(ABC):
 @abstractmethod
 def count_tokens(self,text:str)->int: ...
 @abstractmethod
 def embed_batch(self,texts:list[str])->list[list[float]]: ...
 @property
 @abstractmethod
 def metadata(self)->dict: ...
class DeterministicLocalProvider(EmbeddingProvider):
 def __init__(self,dimension=8): self.dimension=dimension
 def count_tokens(self,text): return len(text.split())
 def validate(self,text):
  if not text.strip(): raise ProviderError("EMPTY_INPUT",False)
 def embed_batch(self,texts):
  output=[]
  for text in texts:
   self.validate(text); raw=hashlib.sha256(text.encode()).digest(); vector=[(raw[i]/255)*2-1 for i in range(self.dimension)]; norm=math.sqrt(sum(x*x for x in vector)) or 1; output.append([x/norm for x in vector])
  return output
 @property
 def metadata(self): return {"provider_type":"LOCAL","provider_name":"deterministic-ci","model_name":"sha256-vector","model_version":"1","dimension":self.dimension,"distance_metric":"COSINE","local_execution":True,"data_handling":"RESTRICTED_ALLOWED"}
