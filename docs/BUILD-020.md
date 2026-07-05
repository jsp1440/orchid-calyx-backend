# BUILD-020 — Connector Execution Framework

## Overview

BUILD-020 establishes the permanent Connector Execution Framework for Calyx, transforming BUILD-019's connector scaffolds into a generic, plugin-based runtime system. This framework enables autonomous capabilities (grant monitoring, literature ingestion, GitHub automation, Gmail processing, database synchronization, AI orchestration, scheduling, and future Orchid Continuum services) to execute through a single unified interface without modifying the core runtime.

## Architecture

### Core Components

#### 1. ConnectorInterface

Abstract base class defining the contract all connectors must implement:

```python
class ConnectorInterface(ABC):
    @property
    def name(self) -> str:
        """Connector name (e.g., 'github', 'gmail', 'openai')"""
        pass

    def health(self) -> dict[str, Any]:
        """Return connector health status"""
        pass

    def execute(self, task: str, **kwargs) -> dict[str, Any]:
        """Execute a task through the connector"""
        pass
```

**Rationale**: Minimal interface ensures simplicity while enforcing essential behaviors. All connectors, regardless of external service, follow this pattern.

#### 2. ConnectorRegistry

Central manager responsible for:

- **Automatic discovery**: Scans `runtime/connectors/` for classes implementing `ConnectorInterface`
- **Initialization**: Instantiates connector classes without manual registration
- **Lifecycle management**: Maintains connector state and lifecycle
- **Execution routing**: Routes tasks to appropriate connectors
- **Health aggregation**: Collects per-connector and aggregate health status
- **Logging**: Centralized audit trail (connector, task, time, success/failure, exceptions)
- **Error handling**: Standardized error propagation and recovery

**Key method**: `discover()` uses Python's `importlib` to dynamically load connector modules.

#### 3. Connector Modules

Each connector is a separate module in `runtime/connectors/` implementing `ConnectorInterface`.

Example structure:
```
runtime/connectors/
  __init__.py
  github_connector.py        # Implements GitHubConnector
  gmail_connector.py         # Implements GmailConnector
  openai_connector.py        # Implements OpenAIConnector
  ...
```

#### 4. REST API Routes

Three core endpoints expose the framework:

**GET /api/connectors**
- Lists all discovered connectors and health status
- Returns: `{"connectors": [{"name": "github", "healthy": true}, ...], "total": N, "healthy": M}`

**GET /api/connectors/health**
- Aggregate health check across all connectors
- Returns detailed per-connector health status, startup time, discovery errors

**POST /api/connectors/execute**
- Execute a task through a connector
- Parameters: `connector` (string), `task` (string), task-specific kwargs
- Returns: `{"status": "success"|"failure", "result": {...}, "error": "...", "execution_time_ms": N, "timestamp": "..."}`

### Error Handling

| Scenario | HTTP Status | Example |
|----------|-------------|----------|
| Connector not found | 404 | Requesting non-existent connector |
| Invalid request (missing params) | 400 | Missing `connector` or `task` |
| Task execution fails | 400 | Connector.execute() raises exception |
| Internal error | 500 | Unexpected registry/framework error |

## Connector Lifecycle

### 1. Discovery Phase

```
Registry.discover()
  ├─ Scan runtime/connectors/*.py
  ├─ For each file:
  │   ├─ Load module dynamically
  │   ├─ Find classes implementing ConnectorInterface
  │   └─ Instantiate and register
  └─ Log discovery_errors for any failures
```

**Result**: `registry.connectors` populated with active connector instances.

### 2. Health Check Phase

```
Registry.health()
  ├─ For each connector:
  │   ├─ Call connector.health()
  │   └─ Collect status
  └─ Aggregate: healthy if all report "healthy", else "degraded"
```

**Result**: Per-connector and aggregate health status.

### 3. Execution Phase

```
Registry.execute(connector_name, task, **kwargs)
  ├─ Verify connector exists → raise ValueError if not
  ├─ Log: "Executing task 'X' on connector 'Y'"
  ├─ Start timer
  ├─ Call connector.execute(task, **kwargs)
  ├─ Log: "Task completed in XXXms"
  └─ Return result with status, result/error, execution_time_ms, timestamp
```

**Failure handling**: Exceptions caught, logged, and returned as `{"status": "failure", "error": "..."}`.

## Logging Strategy

All actions logged to `runtime` logger:

```
DISCOVERY:
  INFO: "Starting connector discovery in /path/to/connectors"
  INFO: "Found 5 potential connector files"
  INFO: "Loaded connector: github (from github_connector.GitHubConnector)"
  ERROR: "Failed to load connectors from X.py: ImportError: ..."

EXECUTION:
  INFO: "Executing task 'list' on connector 'github'"
  INFO: "Task 'list' on 'github' completed in 152.34ms"
  ERROR: "Task 'sync' on 'github' failed: Connection timeout"

HEALTH:
  ERROR: "Failed to get health for connector github: Connection refused"
```

## Backward Compatibility

BUILD-019 connector scaffold endpoints remain fully functional:
- `/api/runner/connector-plans/*`
- `/api/runner/connector-scaffolds/*`

BUILD-020 operates in parallel and does not modify or deprecate BUILD-019 APIs.

## Extension Guide

### Adding a New Connector

1. **Create connector module**

   File: `runtime/connectors/myservice_connector.py`

   ```python
   from runtime.connector_interface import ConnectorInterface
   
   class MyServiceConnector(ConnectorInterface):
       @property
       def name(self) -> str:
           return "myservice"
       
       def health(self) -> dict:
           # Check health, return {"status": "healthy" or "unhealthy", ...}
           pass
       
       def execute(self, task: str, **kwargs) -> dict:
           # Execute task, return {"status": "success" or "failure", "result": {...}}
           pass
   ```

2. **Test the connector**

   ```python
   from runtime.connectors.myservice_connector import MyServiceConnector
   
   connector = MyServiceConnector()
   assert connector.name == "myservice"
   health = connector.health()
   result = connector.execute("mytask")
   ```

3. **Deploy**

   Push to `runtime/connectors/`. Next registry discovery will automatically load it.

### Example: GitHub Connector

```python
from github import Github
from runtime.connector_interface import ConnectorInterface

class GitHubConnector(ConnectorInterface):
    def __init__(self):
        self.client = Github(os.getenv("GITHUB_TOKEN"))
    
    @property
    def name(self) -> str:
        return "github"
    
    def health(self) -> dict:
        try:
            user = self.client.get_user()
            return {"status": "healthy", "user": user.login}
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}
    
    def execute(self, task: str, **kwargs) -> dict:
        if task == "list_repos":
            repos = [r.name for r in self.client.get_user().get_repos()]
            return {"status": "success", "repos": repos}
        elif task == "create_issue":
            repo = self.client.get_repo(kwargs["repo"])
            issue = repo.create_issue(kwargs["title"], kwargs["body"])
            return {"status": "success", "issue_url": issue.html_url}
        else:
            raise ValueError(f"Unknown task: {task}")
```

## API Examples

### List Connectors

```bash
curl -X GET "http://localhost:8000/api/connectors"

# Response
{
  "connectors": [
    {"name": "github", "healthy": true},
    {"name": "gmail", "healthy": true},
    {"name": "openai", "healthy": false}
  ],
  "total": 3,
  "healthy": 2
}
```

### Check Health

```bash
curl -X GET "http://localhost:8000/api/connectors/health"

# Response
{
  "status": "degraded",
  "startup_time": "2026-07-05T12:30:45Z",
  "timestamp": "2026-07-05T12:35:10Z",
  "summary": {
    "total": 3,
    "healthy": 2,
    "unhealthy": 1
  },
  "connectors": {
    "github": {"status": "healthy"},
    "gmail": {"status": "healthy"},
    "openai": {"status": "unhealthy", "error": "API key invalid"}
  },
  "discovery_errors": []
}
```

### Execute Task

```bash
curl -X POST "http://localhost:8000/api/connectors/execute?connector=github&task=list_repos"

# Response
{
  "connector": "github",
  "task": "list_repos",
  "status": "success",
  "result": {
    "repos": ["orchid-calyx-backend", "calyx-frontend", ...]
  },
  "execution_time_ms": 245.67,
  "timestamp": "2026-07-05T12:35:20Z"
}
```

## Testing Strategy

- **Unit tests**: ConnectorInterface, ConnectorRegistry, individual connector implementations
- **Integration tests**: Registry discovery, health checks, execution flow
- **Route tests**: API endpoint validation, error handling
- **Mock connectors**: Test discovery and lifecycle without external dependencies

Run: `pytest tests/test_connector_*.py -v`

## Design Decisions

### Why no central configuration?

Connectors are auto-discovered. Adding a new connector only requires dropping a file in `runtime/connectors/`. No registration, no configuration changes.

### Why dependency injection for registry?

The global registry (`_registry`) is lazily initialized on first API call. This enables testing with mock registries and prevents circular imports.

### Why separate interface from implementation?

Abstract `ConnectorInterface` allows:
- Clear contract for all connectors
- Easy testing with mock implementations
- Future language bindings (connectors in other languages via subprocess/RPC)

### Why async-first execution?

Current implementation is sync. Future versions can wrap `execute()` in `asyncio.run()` for concurrent connector execution without changing the interface.

## Future Enhancements

1. **Async execution**: Concurrent task execution across connectors
2. **Retry logic**: Automatic retry on transient failures
3. **Rate limiting**: Per-connector rate limits
4. **Event stream**: Pub/sub for execution events
5. **Connector versioning**: Support multiple versions of same connector
6. **Hot reload**: Update connectors without restarting runtime
7. **Connector marketplace**: Centralized registry of public connectors

## Validation Checklist

- ✅ Project builds successfully
- ✅ All tests pass
- ✅ Linting passes (if configured)
- ✅ Application starts without runtime errors
- ✅ BUILD-019 endpoints continue to work
- ✅ New endpoints accessible at `/api/connectors`
- ✅ HealthConnector auto-discovered and functional
- ✅ Comprehensive logging enabled
- ✅ Error handling covers all scenarios

## Consolidation Summary (BUILD-019 → BUILD-020)

During BUILD-020, two BUILD-019 implementations were consolidated:

**Removed Duplicates**:
- `ConnectorRuntimeBuilder` (used static `/api/runner/connector-runs`)
- `ConnectorExecutionEngine` (used dynamic `/api/runner/connectors/{slug}`)
- Both had identical core logic with only naming/path differences

**Unified Into**:
- `ConnectorRegistry`: Generic, extensible connector management
- `ConnectorInterface`: Simplified contract (name, health, execute)
- `HealthConnector`: Example implementation for testing

**Rationale**:
- Eliminate code duplication and maintenance burden
- Establish single source of truth for connector lifecycle
- Enable future frameworks (grants, literature, scheduling) to reuse the same pattern
- Simplify testing and debugging

## References

- BUILD-019: Connector Runtime Scaffolds (`docs/BUILD-019-connector-runtime.md`)
- BUILD-018: Connector Planning
- Orchid Continuum Architecture: Future autonomous capabilities
