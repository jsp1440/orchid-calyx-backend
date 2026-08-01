from __future__ import annotations

from dataclasses import dataclass

from .github import GitHubEngineeringClient


@dataclass(frozen=True)
class RepositoryContext:
    files: dict[str, str]
    ref: str

    @property
    def file_count(self) -> int:
        return len(self.files)

    def to_dict(self) -> dict:
        return {"ref": self.ref, "files": self.files, "file_count": self.file_count}


class RepositoryInspector:
    def __init__(self, client: GitHubEngineeringClient) -> None:
        self.client = client

    def inspect(self, paths: list[str], *, ref: str = "main") -> RepositoryContext:
        if not paths:
            raise ValueError("INSPECTION_PATHS_REQUIRED")
        if len(paths) > 20:
            raise ValueError("INSPECTION_PATH_LIMIT_EXCEEDED")
        files: dict[str, str] = {}
        for path in paths:
            files[path] = self.client.get_text_file(path, ref=ref)
        return RepositoryContext(files=files, ref=ref)
