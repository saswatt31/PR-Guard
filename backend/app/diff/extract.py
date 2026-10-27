"""TypeScript/JavaScript function extraction with tree-sitter.

We extract only declarations that can be imported by a test: top-level functions,
top-level arrow/function variables, class methods, and object-literal methods on
exported objects. Nested callbacks and overload signatures are skipped.
"""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import PurePosixPath

import tree_sitter_typescript
from tree_sitter import Language, Node, Parser

from app.diff.models import FunctionInfo

SUPPORTED_EXTENSIONS = {".ts", ".tsx", ".js", ".jsx", ".mts", ".cts"}
MAX_SOURCE_CHARS = 6000
IDENTIFIER_RE = re.compile(r"^[A-Za-z_$][\w$]*$")

_LANGUAGES: dict[str, Language] = {}


def _language(tsx: bool) -> Language:
    key = "tsx" if tsx else "typescript"
    if key not in _LANGUAGES:
        capsule = (
            tree_sitter_typescript.language_tsx()
            if tsx
            else tree_sitter_typescript.language_typescript()
        )
        _LANGUAGES[key] = Language(capsule)
    return _LANGUAGES[key]


def parse_tree(source: str, file_path: str):
    tsx = PurePosixPath(file_path).suffix in {".tsx", ".jsx"}
    # tree-sitter Parser objects are cheap; a fresh one avoids cross-thread state.
    return Parser(_language(tsx)).parse(source.encode("utf-8"))


def extract_functions(source: str, file_path: str) -> list[FunctionInfo]:
    if PurePosixPath(file_path).suffix.lower() not in SUPPORTED_EXTENSIONS:
        return []
    if PurePosixPath(file_path).name.endswith((".d.ts", ".d.mts", ".d.cts")):
        return []

    tree = parse_tree(source, file_path)
    root = tree.root_node
    export_names = _exported_names(root)
    functions: list[FunctionInfo] = []
    seen: set[tuple[str, int]] = set()

    for node in _walk(root):
        candidate = _candidate(node, export_names)
        if candidate is None:
            continue
        declaration, name, body, container, container_node = candidate
        if not name or name == "constructor" or name.startswith("#"):
            continue
        if not IDENTIFIER_RE.match(name) and name != "default":
            # Object string keys aren't directly importable; skip rather than guess.
            continue
        key = (name, declaration.start_byte)
        if key in seen:
            continue
        seen.add(key)

        exported = _is_exported(declaration, name, export_names, container_node)
        qualified = f"{container}.{name}" if container else name
        signature_prefix = "export " if _has_ancestor(declaration, "export_statement") else ""
        if declaration.type == "variable_declarator":
            lexical = declaration.parent
            if lexical is not None and lexical.children:
                keyword = _text(lexical.children[0])
                if keyword in {"const", "let", "var"}:
                    signature_prefix += keyword + " "
        raw_signature = source.encode("utf-8")[declaration.start_byte : body.start_byte]
        signature = " ".join((signature_prefix + raw_signature.decode("utf-8", "replace")).split())
        node_source = source.encode("utf-8")[declaration.start_byte : declaration.end_byte]
        functions.append(
            FunctionInfo(
                name=name,
                qualified_name=qualified,
                file_path=file_path,
                signature=signature[:400],
                source=node_source.decode("utf-8", "replace")[:MAX_SOURCE_CHARS],
                start_line=declaration.start_point[0] + 1,
                end_line=declaration.end_point[0] + 1,
                exported=exported,
                is_async=bool(re.search(r"\basync\b", signature)),
                is_ui=_is_ui(node_source.decode("utf-8", "replace"), file_path, declaration),
                container=container,
            )
        )

    functions.sort(key=lambda fn: (fn.start_line, fn.name))
    return functions


def _candidate(
    node: Node, export_names: set[str]
) -> tuple[Node, str, Node, str | None, Node | None] | None:
    """Return (declaration, name, body, container, container_node)."""

    if node.type in {"function_expression", "arrow_function"}:
        parent = node.parent
        if (
            parent is None
            or parent.type != "export_statement"
            or parent.parent is None
            or parent.parent.type != "program"
            or not any(child.type == "default" for child in parent.children)
        ):
            return None
        body = node.child_by_field_name("body")
        if body is None:
            return None
        return node, "default", body, None, None

    if node.type in {"function_declaration", "generator_function_declaration"}:
        if not _is_top_level_declaration(node):
            return None
        name_node = node.child_by_field_name("name")
        body = node.child_by_field_name("body")
        if body is None:
            return None
        name = _text(name_node) if name_node else "default"
        return node, name, body, None, None

    if node.type == "variable_declarator":
        if not _is_top_level_variable(node):
            return None
        value = node.child_by_field_name("value")
        if value is None or value.type not in {"arrow_function", "function_expression", "function"}:
            return None
        name_node = node.child_by_field_name("name")
        body = value.child_by_field_name("body")
        if body is None:
            return None
        return node, _text(name_node), body, None, None

    if node.type in {"method_definition", "public_field_definition"}:
        if _is_private(node):
            return None
        body, value = _class_or_object_body(node)
        if body is None:
            return None
        name_node = node.child_by_field_name("name")
        name = _text(name_node) if name_node else ""
        container, container_node = _container(node)
        return node, name, body, container, container_node

    if node.type == "pair":
        value = node.child_by_field_name("value")
        if value is None or value.type not in {"arrow_function", "function_expression", "function"}:
            return None
        body = value.child_by_field_name("body")
        if body is None:
            return None
        key = node.child_by_field_name("key")
        container, container_node = _container(node)
        return node, _text(key), body, container, container_node

    if node.type == "assignment_expression":
        if not _is_top_level_assignment(node):
            return None
        right = node.child_by_field_name("right")
        if right is None or right.type not in {"arrow_function", "function_expression", "function"}:
            return None
        body = right.child_by_field_name("body")
        left = node.child_by_field_name("left")
        if body is None or left is None:
            return None
        left_text = _text(left)
        name = left_text.rsplit(".", 1)[-1]
        return node, name, body, None, None

    return None


def _is_private(node: Node) -> bool:
    for child in node.children:
        if child.type == "accessibility_modifier" and child.text in {b"private", b"protected"}:
            return True
    return False


def _class_or_object_body(node: Node) -> tuple[Node | None, Node | None]:
    if node.type == "public_field_definition":
        value = node.child_by_field_name("value")
        if value is None or value.type not in {"arrow_function", "function_expression", "function"}:
            return None, None
        return value.child_by_field_name("body"), value
    return node.child_by_field_name("body"), None


def _is_top_level_declaration(node: Node) -> bool:
    parent = node.parent
    if parent is None:
        return False
    if parent.type == "program":
        return True
    return (
        parent.type == "export_statement"
        and parent.parent is not None
        and parent.parent.type == "program"
    )


def _is_top_level_variable(node: Node) -> bool:
    lexical = node.parent
    if lexical is None or lexical.type not in {"lexical_declaration", "variable_declaration"}:
        return False
    parent = lexical.parent
    if parent is None:
        return False
    if parent.type == "program":
        return True
    return (
        parent.type == "export_statement"
        and parent.parent is not None
        and parent.parent.type == "program"
    )


def _is_top_level_assignment(node: Node) -> bool:
    parent = node.parent
    if parent is None:
        return False
    if parent.type == "expression_statement":
        parent = parent.parent
    return parent is not None and parent.type == "program"


def _container(node: Node) -> tuple[str | None, Node | None]:
    parent = node.parent
    if parent is None:
        return None, None

    if parent.type == "class_body":
        class_node = parent.parent
        if class_node is not None and class_node.type in {"class_declaration", "class"}:
            name_node = class_node.child_by_field_name("name")
            return (_text(name_node) if name_node else "AnonymousClass"), class_node
        return None, None

    if parent.type == "object":
        # Find the variable/assignment that owns this object literal.
        ancestor = parent.parent
        while ancestor is not None and ancestor.type not in {
            "variable_declarator",
            "assignment_expression",
            "pair",
            "program",
        }:
            ancestor = ancestor.parent
        if ancestor is not None and ancestor.type in {
            "variable_declarator",
            "assignment_expression",
        }:
            name_node = ancestor.child_by_field_name(
                "name" if ancestor.type == "variable_declarator" else "left"
            )
            return (_text(name_node).rsplit(".", 1)[-1] if name_node else None), ancestor
    return None, None


def _is_exported(
    declaration: Node, name: str, export_names: set[str], container_node: Node | None
) -> bool:
    if declaration.type == "assignment_expression":
        left = declaration.child_by_field_name("left")
        left_text = _text(left)
        if left_text.startswith("module.exports") or left_text.startswith("exports."):
            return True
    if _has_ancestor(declaration, "export_statement"):
        return True
    if name in export_names:
        return True
    if container_node is not None:
        if _has_ancestor(container_node, "export_statement"):
            return True
        container_name_node = container_node.child_by_field_name("name")
        if container_name_node is None:
            container_name_node = container_node.child_by_field_name("left")
        if container_name_node is not None:
            container_name = _text(container_name_node).rsplit(".", 1)[-1]
            if container_name in export_names:
                return True
    return False


def _exported_names(root: Node) -> set[str]:
    names: set[str] = set()
    for node in _walk(root):
        if node.type != "export_statement":
            continue
        clause = next((c for c in node.children if c.type == "export_clause"), None)
        if clause is None:
            continue
        for child in _walk(clause):
            if child.type in {"identifier", "property_identifier"}:
                names.add(_text(child))
    return names


def _has_ancestor(node: Node, type_name: str) -> bool:
    current = node.parent
    while current is not None:
        if current.type == type_name:
            return True
        current = current.parent
    return False


def _is_ui(source: str, file_path: str, node: Node) -> bool:
    path = PurePosixPath(file_path)
    if path.suffix in {".tsx", ".jsx"}:
        return True
    parts = set(path.parts)
    if parts & {"app", "pages", "components"}:
        return True
    return any(child.type.startswith("jsx_") for child in _walk(node))


def _text(node: Node | None) -> str:
    if node is None:
        return ""
    return node.text.decode("utf-8", "replace") if node.text else ""


def _walk(root: Node):
    """Depth-first traversal; tree-sitter cursors are not iterable on all versions."""

    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(reversed(node.children))


def mark_only_changed(
    functions: list[FunctionInfo],
    changed_lines: set[int],
    is_new_file: bool,
    added_lines: set[int] | None = None,
) -> list[FunctionInfo]:
    """Return functions intersecting changed new-file lines, with ``is_new`` set."""

    added = added_lines if added_lines is not None else changed_lines
    changed: list[FunctionInfo] = []
    for function in functions:
        if is_new_file:
            changed.append(replace(function, is_new=True))
            continue
        if _overlaps(function.start_line, function.end_line, changed_lines):
            whole_range = set(range(function.start_line, function.end_line + 1))
            is_new = bool(whole_range) and whole_range.issubset(added)
            changed.append(replace(function, is_new=is_new))
    return changed


def _overlaps(start: int, end: int, lines: set[int]) -> bool:
    return any(line in lines for line in range(start, end + 1))
