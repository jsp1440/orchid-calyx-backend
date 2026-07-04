from runtime.brain_integration import BrainIntegrationWorker
from runtime.runtime_executor import RuntimeExecutor


def test_engineering_memory_harvester_returns_repository_summary():
    worker = BrainIntegrationWorker(
        {
            "module_id": "CDS-ENG-001",
            "module_name": "EngineeringMemoryHarvester",
            "job_name": "cds:CDS-ENG-001",
        }
    )
    result = worker.engineering_memory_harvester()

    assert result["module"] == "EngineeringMemoryHarvester"
    assert result["status"] == "completed"
    assert "memory_objects_created" in result


def test_dependency_intelligence_returns_graph_counts():
    worker = BrainIntegrationWorker(
        {
            "module_id": "CDS-SCI-001",
            "module_name": "DependencyIntelligence",
            "job_name": "cds:CDS-SCI-001",
        }
    )
    result = worker.dependency_intelligence()

    assert result["module"] == "DependencyIntelligence"
    assert result["status"] == "completed"
    assert result["node_count"] >= 1


def test_executor_uses_brain_worker_for_database_inspector(tmp_path):
    executor = RuntimeExecutor(execution_dir=tmp_path)
    result = executor.execute_module("DatabaseInspector")

    assert result["build"] == "BUILD-013"
    assert result["execution"]["module_name"] == "DatabaseInspector"
    assert result["execution"]["result"]["module"] == "DatabaseInspector"
