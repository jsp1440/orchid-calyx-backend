from .repository import MemoryCandidateRepository
from app.persistence.state_repository import PostgresStateMixin
class PostgresCandidateRepository(PostgresStateMixin,MemoryCandidateRepository):
 snapshot_kind="candidate_knowledge";lock_id=8601;state_attributes=("runs","items","candidates","evidence_links","reviews","conflicts","duplicate_groups","events","cancelled","_id")
 def __init__(self,database_url=None):MemoryCandidateRepository.__init__(self);self.__init_persistence__(database_url);self.refresh()
