"""BUILD-014 autonomous discovery engine.

This module lets Calyx inspect its own repository and derive a live capability
inventory without requiring every runtime component to be manually registered.
The first implementation is deterministic, dependency-light, and safe for
Render: it scans Python files, discovers routers/workers/classes/metadata, and
builds a capability registry, graph, schedule, and recommendations.
"""

from __future__ import annotations

import ast
import json
from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DISCOVERY_CACHE = REPO_ROOT / "runtime" / "discovery_registry.json"


CATEGORY_RULES = {
    "router": "api",
    "worker": "worker",
    "executor": "runtime",
    "planner": "runtime",
    "discovery": "runtime",
    "brain": "brain",
    "scheduler": "runtime",
    "config": "configuration",
    "infrastructure": "infrastructure",
}


@dataclass
class ModuleDescriptor:
    name: str
    path: str
    category: str
    module_type: str
    description: str | None = None
    classes: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    api_routes: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    health: str = "healthy"
    tags: list[str] = field(default_factory=list)


class DiscoveryEngine:
    """Discover runtime modules, capabilities, graph, and recommendations."""

    def __init__(self, repo_root: Path | None = None, cache_path: Path | None = None) -> None:
        self.repo_root = repo_root or REPO_ROOT
        self.cache_path = cache_path or DISCOVERY_CACHE

    def discover(self, write_cache: bool = True) -> dict[str, Any]:
        modules = [self._inspect_python_file(path) for path in self._python_files()]
        modules = [module for module in modules if module is not None]
        capabilities = self.capabilities_from_modules(modules)
        graph = self.dependency_graph(modules)
        schedule = self.schedule_from_graph(modules, graph)
        recommendations = self.recommendations(modules, graph, schedule)
        result = {
            "build": "BUILD-014",
            "generated_at": utc_now(),
            "module_count": len(modules),
            "capability_count": len(capabilities),
            "modules": [asdict(module) for module in modules],
            "capabilities": capabilities,
            "graph": graph,
            "schedule": schedule,
            "recommendations": recommendations,
            "dashboard": self.dashboard(modules, capabilities, graph, recommendations),
        }
        if write_cache:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        return result

    def cached_or_discover(self) -> dict[str, Any]:
        if self.cache_path.exists():
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        return self.discover(write_cache=True)

    def modules(self) -> dict[str, Any]:
        data = self.cached_or_discover()
        return {"build": "BUILD-014", "modules": data.get("modules", []), "module_count": data.get("module_count", 0)}

    def capabilities(self) -> dict[str, Any]:
        data = self.cached_or_discover()
        return {
            "build": "BUILD-014",
            "capabilities": data.get("capabilities", []),
            "capability_count": data.get("capability_count", 0),
        }

    def graph(self) -> dict[str, Any]:
        data = self.cached_or_discover()
        return {"build": "BUILD-014", **data.get("graph", {})}

    def schedule(self) -> dict[str, Any]:
        data = self.cached_or_discover()
        return {"build": "BUILD-014", **data.get("schedule", {})}

    def recommendation_report(self) -> dict[str, Any]:
        data = self.cached_or_discover()
        return {"build": "BUILD-014", "recommendations": data.get("recommendations", [])}

    def dashboard_report(self) -> dict[str, Any]:
        data = self.cached_or_discover()
        return {"build": "BUILD-014", **data.get("dashboard", {})}

    def capabilities_from_modules(self, modules: list[ModuleDescriptor]) -> list[dict[str, Any]]:
        capabilities: list[dict[str, Any]] = []
        for module in modules:
            for capability in module.capabilities:
                capabilities.append(
                    {
                        "name": capability,
                        "module": module.name,
                        "category": module.category,
                        "source_file": module.path,
                        "health": module.health,
                        "dependencies": module.dependencies,
                        "tags": module.tags,
                    }
                )
        return capabilities

    def dependency_graph(self, modules: list[ModuleDescriptor]) -> dict[str, Any]:
        names = {module.name for module in modules}
        nodes = [
            {
                "id": module.name,
                "path": module.path,
                "category": module.category,
                "health": module.health,
            }
            for module in modules
        ]
        edges = []
        missing = []
        for module in modules:
            for dependency in module.dependencies:
                target = self._match_dependency(dependency, names)
                if target:
                    edges.append({"from": target, "to": module.name, "type": "import"})
                else:
                    missing.append({"module": module.name, "dependency": dependency})
        cycles = self._detect_cycles([node["id"] for node in nodes], edges)
        return {
            "nodes": nodes,
            "edges": edges,
            "missing_dependencies": missing,
            "cycles": cycles,
            "node_count": len(nodes),
            "edge_count": len(edges),
        }

    def schedule_from_graph(self, modules: list[ModuleDescriptor], graph: dict[str, Any]) -> dict[str, Any]:
        nodes = [node["id"] for node in graph.get("nodes", [])]
        indegree = {node: 0 for node in nodes}
        children: dict[str, list[str]] = defaultdict(list)
        for edge in graph.get("edges", []):
            parent = edge["from"]
            child = edge["to"]
            children[parent].append(child)
            indegree[child] = indegree.get(child, 0) + 1
        ready = deque(sorted([node for node, degree in indegree.items() if degree == 0]))
        ordered: list[str] = []
        while ready:
            node = ready.popleft()
            ordered.append(node)
            for child in sorted(children.get(node, [])):
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)
        blocked = sorted([node for node in nodes if node not in ordered])
        module_index = {module.name: module for module in modules}
        queue = [
            {
                "rank": index + 1,
                "module": name,
                "category": module_index[name].category,
                "health": module_index[name].health,
                "action": f"Run discovered capability module {name}",
            }
            for index, name in enumerate(ordered)
        ]
        return {
            "status": "ready" if not blocked else "blocked",
            "queue_depth": len(queue),
            "queue": queue,
            "blocked": blocked,
        }

    def recommendations(
        self,
        modules: list[ModuleDescriptor],
        graph: dict[str, Any],
        schedule: dict[str, Any],
    ) -> list[dict[str, Any]]:
        recommendations: list[dict[str, Any]] = []
        missing = graph.get("missing_dependencies", [])
        cycles = graph.get("cycles", [])
        if missing:
            recommendations.append(
                {
                    "priority": "HIGH",
                    "recommendation": "Normalize or register missing dependencies",
                    "reason": f"{len(missing)} discovered dependencies do not map to known modules.",
                }
            )
        if cycles:
            recommendations.append(
                {
                    "priority": "HIGH",
                    "recommendation": "Resolve dependency cycles before autonomous scheduling",
                    "reason": f"{len(cycles)} dependency cycles were detected.",
                }
            )
        categories = Counter(module.category for module in modules)
        if categories.get("brain", 0) > 0:
            recommendations.append(
                {
                    "priority": "HIGH",
                    "recommendation": "Run Brain-aware inspections on a recurring schedule",
                    "reason": f"{categories['brain']} Brain-related modules are discoverable.",
                }
            )
        if schedule.get("queue_depth", 0) > 0:
            recommendations.append(
                {
                    "priority": "MEDIUM",
                    "recommendation": "Use discovery schedule to seed the RuntimeExecutor queue",
                    "reason": f"{schedule['queue_depth']} modules are schedulable from autonomous discovery.",
                }
            )
        recommendations.append(
            {
                "priority": "MEDIUM",
                "recommendation": "Persist discovery snapshots into Engineering Memory",
                "reason": "Discovery currently caches to repository runtime JSON; BUILD-015 should store longitudinal history.",
            }
        )
        return recommendations

    def dashboard(
        self,
        modules: list[ModuleDescriptor],
        capabilities: list[dict[str, Any]],
        graph: dict[str, Any],
        recommendations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        category_counts = Counter(module.category for module in modules)
        health_counts = Counter(module.health for module in modules)
        return {
            "modules": len(modules),
            "capabilities": len(capabilities),
            "category_counts": dict(category_counts),
            "health_counts": dict(health_counts),
            "failed": health_counts.get("failed", 0),
            "degraded": health_counts.get("degraded", 0),
            "healthy": health_counts.get("healthy", 0),
            "execution_graph_nodes": graph.get("node_count", 0),
            "execution_graph_edges": graph.get("edge_count", 0),
            "recommendations": len(recommendations),
        }

    def _python_files(self) -> list[Path]:
        roots = [self.repo_root / "runtime", self.repo_root / "app"]
        files: list[Path] = []
        for root in roots:
            if root.exists():
                files.extend(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)
        return sorted(files)

    def _inspect_python_file(self, path: Path) -> ModuleDescriptor | None:
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except Exception:
            return ModuleDescriptor(
                name=path.stem,
                path=str(path.relative_to(self.repo_root)),
                category="unknown",
                module_type="python",
                health="failed",
                tags=["parse_failed"],
            )

        classes: list[str] = []
        functions: list[str] = []
        imports: list[str] = []
        routes: list[str] = []
        module_info: dict[str, Any] = {}
        docstring = ast.get_docstring(tree)

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                classes.append(node.name)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.append(node.name)
                for decorator in node.decorator_list:
                    route = self._route_from_decorator(decorator)
                    if route:
                        routes.append(route)
            elif isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "MODULE_INFO":
                        try:
                            value = ast.literal_eval(node.value)
                            if isinstance(value, dict):
                                module_info = value
                        except Exception:
                            pass

        name = str(module_info.get("name") or self._module_name_from_path(path))
        category = str(module_info.get("category") or self._infer_category(path, classes, functions, routes))
        dependencies = module_info.get("dependencies") or self._runtime_import_dependencies(imports)
        tags = module_info.get("tags") or self._infer_tags(path, classes, functions, routes)
        capabilities = module_info.get("outputs") or self._infer_capabilities(name, path, classes, functions, routes)
        module_type = "api_router" if routes else "python_module"
        if any("Worker" in class_name for class_name in classes):
            module_type = "worker"
        if any("Executor" in class_name for class_name in classes):
            module_type = "executor"
        return ModuleDescriptor(
            name=name,
            path=str(path.relative_to(self.repo_root)),
            category=category,
            module_type=module_type,
            description=str(module_info.get("description") or docstring or "").strip()[:500] or None,
            classes=sorted(classes),
            functions=sorted(functions),
            imports=sorted(set(imports)),
            api_routes=sorted(routes),
            dependencies=sorted(set(str(item) for item in dependencies)),
            capabilities=sorted(set(str(item) for item in capabilities)),
            health="healthy",
            tags=sorted(set(str(item) for item in tags)),
        )

    def _module_name_from_path(self, path: Path) -> str:
        return path.stem.replace("_", "-")

    def _infer_category(self, path: Path, classes: list[str], functions: list[str], routes: list[str]) -> str:
        text = " ".join([str(path), *classes, *functions]).lower()
        if routes:
            return "api"
        for key, category in CATEGORY_RULES.items():
            if key in text:
                return category
        return "runtime"

    def _infer_tags(self, path: Path, classes: list[str], functions: list[str], routes: list[str]) -> list[str]:
        tags = [self._infer_category(path, classes, functions, routes)]
        if routes:
            tags.append("fastapi")
        if classes:
            tags.append("classes")
        return tags

    def _infer_capabilities(
        self,
        name: str,
        path: Path,
        classes: list[str],
        functions: list[str],
        routes: list[str],
    ) -> list[str]:
        capabilities = []
        if routes:
            capabilities.append("Expose API routes")
        for class_name in classes:
            if class_name.endswith("Worker"):
                capabilities.append(f"Run {class_name}")
            elif class_name.endswith("Engine"):
                capabilities.append(f"Operate {class_name}")
            elif class_name.endswith("Planner"):
                capabilities.append(f"Plan with {class_name}")
            elif class_name.endswith("Executor"):
                capabilities.append(f"Execute with {class_name}")
            elif class_name.endswith("Loader"):
                capabilities.append(f"Load with {class_name}")
        if not capabilities:
            capabilities.append(f"Provide {name} runtime behavior")
        return capabilities

    def _runtime_import_dependencies(self, imports: list[str]) -> list[str]:
        dependencies = []
        for item in imports:
            if item.startswith("runtime."):
                dependencies.append(item.split(".")[-1].replace("_", "-"))
            elif item.startswith("app."):
                dependencies.append(item.split(".")[-1].replace("_", "-"))
        return dependencies

    def _route_from_decorator(self, decorator: ast.AST) -> str | None:
        if not isinstance(decorator, ast.Call):
            return None
        func = decorator.func
        if not isinstance(func, ast.Attribute):
            return None
        if func.attr not in {"get", "post", "put", "delete", "patch"}:
            return None
        if not decorator.args:
            return f"{func.attr.upper()} <unknown>"
        arg = decorator.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return f"{func.attr.upper()} {arg.value}"
        return f"{func.attr.upper()} <dynamic>"

    def _match_dependency(self, dependency: str, names: set[str]) -> str | None:
        normalized = dependency.lower().replace("_", "-")
        for name in names:
            if normalized == name.lower().replace("_", "-"):
                return name
        return None

    def _detect_cycles(self, nodes: list[str], edges: list[dict[str, str]]) -> list[list[str]]:
        adjacency: dict[str, list[str]] = defaultdict(list)
        for edge in edges:
            adjacency[edge["from"]].append(edge["to"])
        visited: set[str] = set()
        stack: set[str] = set()
        cycles: list[list[str]] = []

        def visit(node: str, path: list[str]) -> None:
            visited.add(node)
            stack.add(node)
            for child in adjacency.get(node, []):
                if child not in visited:
                    visit(child, [*path, child])
                elif child in stack:
                    try:
                        start = path.index(child)
                        cycles.append(path[start:] + [child])
                    except ValueError:
                        cycles.append([node, child])
            stack.discard(node)

        for node in nodes:
            if node not in visited:
                visit(node, [node])
        return cycles


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
