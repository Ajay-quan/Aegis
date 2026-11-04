"""Static guarantee: every call from a tenant wrapper into the raw store runs inside
tenant_context(), so Postgres RLS always sees the right tenant."""
import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "adapters" / "tenancy.py"


def _inner_calls_outside_context(tree: ast.AST) -> list[int]:
    bad: list[int] = []

    def visit(node: ast.AST, inside: bool) -> None:
        if isinstance(node, (ast.With, ast.AsyncWith)):
            inside = inside or any(
                isinstance(i.context_expr, ast.Call) and getattr(i.context_expr.func, "id", "") == "tenant_context"
                for i in node.items)
        if (isinstance(node, ast.Attribute) and node.attr not in ("tenant_id",)
                and isinstance(node.value, ast.Attribute) and node.value.attr == "_inner"
                and isinstance(node.value.value, ast.Name) and node.value.value.id == "self" and not inside):
            bad.append(node.lineno)
        for child in ast.iter_child_nodes(node):
            visit(child, inside)

    for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
        for fn in [n for n in cls.body if isinstance(n, ast.AsyncFunctionDef)]:
            visit(fn, False)
    return bad


def test_all_inner_store_calls_are_tenant_bound():
    bad = _inner_calls_outside_context(ast.parse(SRC.read_text()))
    assert not bad, f"self._inner.* used outside tenant_context at lines {bad}"
