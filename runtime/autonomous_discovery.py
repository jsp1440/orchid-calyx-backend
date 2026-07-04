"""BUILD-014 autonomous discovery engine.

Calyx can inspect its own repository, derive module/capability metadata,
build a dependency graph, and recommend next runtime actions without requiring
every component to be manually registered.
"""

from __future__ import annotations

import ast
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .runtime_planner import RuntimePlanner

REPO_ROOT = Path(__file__).resolve().parents[1]
DISCOVERY_CACHE = REPO_ROOT / "runtime" / "discovery_registry.json"
SCAN_DIRS = ["runtime", "app"]


@dataclass
class DiscoveredModule:
    name: str
    path: str
    module_type: str
    category: str
    status: str
    capabilities: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    routers: list[str] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)


@dataclass
class Capability:
    name: str
    provider: str
    category: str
    description: str
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    health: str = "unknown"


@dataclass
class Recommendation:
    priority: str
    recommendation: str
    reason: str
    source: str


class AutonomousDiscoveryEngine:
    """Discover runtime modules and derive operational metadata."""

    def __init__(self, repo_root: Path | None = None, cache_path: Path | None = None) -> None:
        self.repo_root = repo_root or REPO_ROOT
        self.cache_path = cache_path or DISCOVERY_CACHE

    def discover(self, write_cache: bool = True) -> dict[str, Any]:
        modules = self._discover_python_modules()
        capabilities = self._capabilities_from_modules(modules)
        graph = self._dependency_graph(modules)
        recommendations = self._recommendations(modules, capabilities, graph)
        payload = {
            "build": "BUILD-014",
            "status": "discovered",
            "summary": self._summary(modules, capabilities, graph, recommendations),
            "modules": [asdict(module) for module in modules],
            "capabilities": [asdict(capability) for capability in capabilities],
            "graph": graph,
            "recommendations": [asdict(item) for item in recommendations],
        }
        if write_cache:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return payload

    def cached_or_discover(self) -> dict[str, Any]:
        if self.cache_path.exists():
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        return self.discover(write_cache=True)

    def modules(self) -> dict[str, Any]:
        payload = self.cached_or_discover()
        return {"build": "BUILD-014", "count": len(payload.get("modules", [])), "modules": payload.get("modules", [])}

    def capabilities(self) -> dict[str, Any]:
        payload = self.cached_or_discover()
        return {"build": "BUILD-014", "count": len(payload.get("capabilities", [])), "capabilities": payload.get("capabilities", [])}

    def graph(self) -> dict[str, Any]:
        payload = self.cached_or_discover()
        return {"build": "BUILD-014", **payload.get("graph", {})}

    def recommendations(self) -> dict[str, Any]:
        payload = self.cached_or_discover()
        items = payload.get("recommendations", [])
        return {"build": "BUILD-014", "count": len(items), "recommendations": items}

    def schedule(self) -> dict[str, Any]:
        payload = self.cached_or_discover()
        nodes = payload.get("graph", {}).get("nodes", [])
        healthy = [node for node in nodes if node.get("health") in {"healthy", "available"}]
        return {
            "build": "BUILD-014",
            "status": "scheduled",
            "queue_depth": len(healthy),
            "schedule": [
                {"rank": idx + 1, "module": node["name"], "reason": "healthy discovered capability"}
                for idx, node in enumerate(healthy)
            ],
            "top_recommendations": payload.get("recommendations", [])[:5],
        }

    def _discover_python_modules(self) -> list[DiscoveredModule]:
        discovered: list[DiscoveredModule] = []
        for scan_dir in SCAN_DIRS:
            root = self.repo_root / scan_dir
            if not root.exists():
                continue
            for path in sorted(root.rglob("*.py")):
                if "__pycache__" in path.parts:
                    continue
                module = self._inspect_python_file(path)
                if module:
                    discovered.append(module)
        return discovered

    def _inspect_python_file(self, path: Path) -> DiscoveredModule | None:
        rel = path.relative_to(self.repo_root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except Exception:
            return DiscoveredModule(path.stem, rel, "python_module", "Unknown", "degraded")

        classes = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
        functions = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
        imports = self._imports(tree)
        routers = self._routes(tree)
        module_info = self._module_info(tree)
        name = module_info.get("name") or self._friendly_name(path, classes)
        category = module_info.get("category") or self._category_for_path(rel, classes, routers)
        module_type = self._module_type(rel, classes, routers)
        capabilities = module_info.get("capabilities") or self._infer_capabilities(name, rel, classes, functions, routers)
        dependencies = module_info.get("dependencies") or imports
        status = "healthy" if capabilities or routers or classes else "available"
        return DiscoveredModule(
            name=name,
            path=rel,
            module_type=module_type,
            category=category,
            status=status,
            capabilities=capabilities,
            dependencies=dependencies[:25],
            routers=routers,
            classes=classes[:25],
            functions=functions[:25],
        )

    def _imports(self, tree: ast.AST) -> list[str]:
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        return sorted(set(imports))

    def _routes(self, tree: ast.AST) -> list[str]:
        routes: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for decorator in node.decorator_list:
                    route = self._route_from_decorator(decorator)
                    if route:
                        routes.append(route)
        return routes

    def _route_from_decorator(self, decorator: ast.AST) -> str | None:
        if not isinstance(decorator, ast.Call):
            return None
        if not isinstance(decorator.func, ast.Attribute):
            return None
        if decorator.func.attr not in {"get", "post", "put", "delete", "patch"}:
            return None
        if not decorator.args or not isinstance(decorator.args[0], ast.Constant):
            return None
        return f"{decorator.func.attr.upper()} {decorator.args[0].value}"

    def _module_info(self, tree: ast.AST) -> dict[str, Any]:
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "MODULE_INFO":
                        try:
                            value = ast.literal_eval(node.value)
                            return value if isinstance(value, dict) else {}
                        except Exception:
                            return {}
        return {}

    def _friendly_name(self, path: Path, classes: list[str]) -> str:
        preferred = [name for name in classes if name.endswith(("Engine", "Worker", "Service", "Planner", "Executor"))]
        if preferred:
            return preferred[0]
        if classes:
            return classes[0]
        return "".join(part.capitalize() for part in path.stem.split("_"))

    def _category_for_path(self, rel: str, classes: list[str], routers: list[str]) -> str:
        lowered = rel.lower()
        joined = " ".join(classes).lower()
        if routers or "router" in lowered:
            return "API"
        if "brain" in lowered or "brain" in joined:
            return "Brain"
        if "executor" in lowered or "worker" in lowered:
            return "Execution"
        if "planner" in lowered or "discovery" in lowered:
            return "Planning"
        if "config" in lowered:
            return "Configuration"
        return "Runtime"

    def _module_type(self, rel: str, classes: list[str], routers: list[str]) -> str:
        lowered = rel.lower()
        if routers or "router" in lowered:
            return "api_router"
        if any(name.endswith("Worker") for name in classes):
            return "worker"
        if any(name.endswith("Engine") for name in classes):
            return "engine"
        if any(name.endswith("Service") for name in classes):
            return "service"
        return "python_module"

    def _infer_capabilities(self, name: str, rel: str, classes: list[str], functions: list[str], routers: list[str]) -> list[str]:
        caps: list[str] = []
        lowered = f"{name} {rel} {' '.join(classes)} {' '.join(functions)}".lower()
        if routers:
            caps.append("Expose API endpoints")
        if "database" in lowered or "brain" in lowered:
            caps.append("Inspect Brain state")
        if "planner" in lowered or "plan" in lowered:
            caps.append("Plan runtime work")
        if "executor" in lowered or "execute" in lowered:
            caps.append("Execute runtime work")
        if "discovery" in lowered or "discover" in lowered:
            caps.append("Discover runtime capabilities")
        if "memory" in lowered:
            caps.append("Harvest engineering memory")
        if "dependency" in lowered:
            caps.append("Analyze dependencies")
        if not caps and classes:
            caps.append("Provide runtime component")
        return sorted(set(caps))

    def _capabilities_from_modules(self, modules: list[DiscoveredModule]) -> list[Capability]:
        capabilities: list[Capability] = []
        for module in modules:
            for cap in module.capabilities:
                inputs = []
                joined = f"{module.name} {module.path} {cap}".lower()
                if "database" in joined or "brain" in joined:
                    inputs.append("DATABASE_URL")
                if module.routers:
                    inputs.append("HTTP request")
                capabilities.append(
                    Capability(
                        name=cap,
                        provider=module.name,
                        category=module.category,
                        description=f"{module.name} provides: {cap}",
                        inputs=inputs,
                        outputs=[cap],
                        dependencies=module.dependencies,
                        health="healthy" if module.status == "healthy" else "available",
                    )
                )
        return capabilities

    def _dependency_graph(self, modules: list[DiscoveredModule]) -> dict[str, Any]:
        nodes = [
            {
                "name": module.name,
                "path": module.path,
                "type": module.module_type,
                "category": module.category,
                "health": "healthy" if module.status == "healthy" else "available",
            }
            for module in modules
        ]
        module_names = {module.name.lower().replace("_", ""): module.name for module in modules}
        edges: list[dict[str, str]] = []
        missing: list[dict[str, str]] = []
        for module in modules:
            for dep in module.dependencies:
                dep_key = dep.split(".")[-1].lower().replace("_", "")
                matched = None
                for key, candidate in module_names.items():
                    if dep_key and (dep_key in key or key in dep_key):
                        matched = candidate
                        break
                if matched and matched != module.name:
                    edges.append({"from": matched, "to": module.name, "type": "import"})
                elif dep.startswith(("runtime", "app")):
                    missing.append({"module": module.name, "dependency": dep})
        return {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "nodes": nodes,
            "edges": edges,
            "missing_dependencies": missing[:100],
            "cycles": [],
        }

    def _recommendations(self, modules: list[DiscoveredModule], capabilities: list[Capability], graph: dict[str, Any]) -> list[Recommendation]:
        recs: list[Recommendation] = []
        if graph.get("missing_dependencies"):
            recs.append(Recommendation("MEDIUM", "Normalize internal dependency declarations", f"{len(graph['missing_dependencies'])} internal dependency hints were not matched to modules.", "dependency_graph"))
        if not any(cap.name == "Discover runtime capabilities" for cap in capabilities):
            recs.append(Recommendation("HIGH", "Register discovery capability", "Discovery engine capability is not visible.", "capability_registry"))
        try:
            queue = RuntimePlanner().queue()
            if queue.get("queue_depth", 0) > 0:
                recs.append(Recommendation("HIGH", "Execute planner queue", f"{queue.get('queue_depth')} planner-selected modules are ready to run.", "runtime_planner"))
        except Exception:
            recs.append(Recommendation("MEDIUM", "Check RuntimePlanner", "Planner queue could not be evaluated.", "runtime_planner"))
        recs.append(Recommendation("LOW", "Persist discovery results into Brain memory", "BUILD-014 writes a file-backed cache; BUILD-015 should persist discovery snapshots.", "brain_sync"))
        return recs

    def _summary(self, modules: list[DiscoveredModule], capabilities: list[Capability], graph: dict[str, Any], recommendations: list[Recommendation]) -> dict[str, Any]:
        healthy = len([module for module in modules if module.status == "healthy"])
        return {
            "modules": len(modules),
            "capabilities": len(capabilities),
            "healthy": healthy,
            "degraded": len([module for module in modules if module.status == "degraded"]),
            "graph_nodes": graph.get("node_count", 0),
            "graph_edges": graph.get("edge_count", 0),
            "recommendations": len(recommendations),
            "brain_connected": any("DATABASE_URL" in cap.inputs for cap in capabilities),
        }
