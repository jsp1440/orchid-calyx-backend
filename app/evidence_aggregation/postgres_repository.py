from .repository import MemoryAggregateRepository
from app.persistence.state_repository import PostgresStateMixin
class PostgresAggregateRepository(PostgresStateMixin,MemoryAggregateRepository):
 snapshot_kind="evidence_aggregation";lock_id=8602;state_attributes=("runs","items","clusters","members","aggregates","versions","evidence","relationships","independence","conflicts","reviews","warnings","events","tombstones","rulesets","models","cancelled","_id")
 def __init__(self,database_url=None):MemoryAggregateRepository.__init__(self);self.__init_persistence__(database_url);self.refresh()
