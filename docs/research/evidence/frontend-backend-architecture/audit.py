"""Inspect source boundaries and OpenAPI without starting a worker or model call."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import tempfile
from collections import Counter
from pathlib import Path


def inspect_sources(root: Path) -> dict:
    groups = {
        "python": (root / "src/texlate", {".py"}),
        "web": (root / "web/src", {".ts", ".tsx"}),
        "zotero": (root / "zotero/src", {".ts", ".tsx"}),
    }
    result = {}
    digest = hashlib.sha256()
    imports = Counter()
    for name, (directory, extensions) in groups.items():
        paths = sorted(p for p in directory.rglob("*") if p.suffix in extensions)
        production = [p for p in paths if "test" not in p.relative_to(directory).parts]
        result[name] = {
            "files": len(paths),
            "lines": sum(len(p.read_bytes().splitlines()) for p in paths),
            "files_excluding_test_directory": len(production),
        }
        for path in paths:
            data = path.read_bytes()
            digest.update(str(path.relative_to(root)).encode() + b"\0" + data + b"\0")
            if path.suffix != ".py":
                continue
            owner = path.relative_to(directory).parts[0].removesuffix(".py")
            for node in ast.walk(ast.parse(data, filename=str(path))):
                modules = (
                    [node.module or ""]
                    if isinstance(node, ast.ImportFrom)
                    else [a.name for a in node.names]
                    if isinstance(node, ast.Import)
                    else []
                )
                for module in modules:
                    if module.startswith("texlate."):
                        target = module.split(".")[1]
                        if target != owner:
                            imports[f"{owner} -> {target}"] += 1
    return {
        "scope": result,
        "source_tree_sha256": digest.hexdigest(),
        "absolute_cross_domain_import_statements": dict(sorted(imports.items())),
        "import_limit": "Includes TYPE_CHECKING; excludes relative and dynamic imports",
    }


def inspect_openapi() -> dict:
    from texlate.server.app import create_app

    with tempfile.TemporaryDirectory(prefix="texlate-contract-audit-") as tmp:
        schema = create_app(data_dir=Path(tmp), start_worker=False).openapi()
    operations = []
    for path, item in schema["paths"].items():
        for method, operation in item.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            success = {
                code: response.get("content", {})
                .get("application/json", {})
                .get("schema", {})
                for code, response in operation.get("responses", {}).items()
                if code.startswith("2")
            }
            operations.append(
                {
                    "method": method.upper(),
                    "path": path,
                    "request_body_declared": "requestBody" in operation,
                    "success_json_schemas": success,
                }
            )
    components = schema.get("components", {}).get("schemas", {})
    return {
        "operations": len(operations),
        "request_bodies_declared": sum(o["request_body_declared"] for o in operations),
        "business_object_schemas_with_properties": [
            name
            for name, value in components.items()
            if value.get("properties")
            and name not in {"HTTPValidationError", "ValidationError"}
        ],
        "components": sorted(components),
        "operation_details": operations,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[4]
    report = {
        "observed_on": "2026-10-18",
        "git_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip(),
        "basis": "Working tree, including uncommitted product changes; not a release benchmark",
        **inspect_sources(root),
        "openapi": inspect_openapi(),
    }
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "scope": report["scope"],
                "openapi_operations": report["openapi"]["operations"],
            }
        )
    )


if __name__ == "__main__":
    main()
