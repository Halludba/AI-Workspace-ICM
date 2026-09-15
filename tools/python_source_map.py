#!/usr/bin/env python3
"""Shared deterministic Python source-map primitive.

This module owns Python AST definition-range extraction so token profiling and
source navigation do not maintain competing parsers.
"""
from __future__ import annotations

import ast


class SourceMapError(ValueError):
    pass


def build_python_source_map(text: str) -> dict:
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        raise SourceMapError(f"cannot parse Python source: {exc}") from exc

    symbols: list[dict] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.scope: list[str] = []

        def _definition(self, node: ast.AST, *, name: str, kind: str, is_async: bool = False) -> None:
            end = getattr(node, "end_lineno", None)
            line = getattr(node, "lineno", None)
            if line is None or end is None:
                return
            decorators = getattr(node, "decorator_list", [])
            starts = [line, *(getattr(item, "lineno", line) for item in decorators)]
            qualified = ".".join([*self.scope, name])
            symbols.append({
                "name": name,
                "qualified_name": qualified,
                "kind": kind,
                "async": is_async,
                "line_start": min(starts),
                "line_end": end,
            })
            self.scope.append(name)
            self.generic_visit(node)
            self.scope.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._definition(node, name=node.name, kind="function")

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._definition(node, name=node.name, kind="function", is_async=True)

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self._definition(node, name=node.name, kind="class")

    Visitor().visit(tree)
    symbols.sort(key=lambda item: (item["line_start"], item["line_end"], item["qualified_name"]))
    return {"schema_version": "1.0", "language": "python", "symbols": symbols}
