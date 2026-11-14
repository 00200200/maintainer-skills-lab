//! Syntax-only outlines. No filesystem access, name resolution or dependency graph.

use pyo3::exceptions::{PyRuntimeError, PySyntaxError, PyValueError};
use pyo3::prelude::*;
use std::collections::HashSet;
use std::path::Path;
use tree_sitter::{Language, Node, Parser};

/// Read-only symbol record; line numbers are one-based and inclusive.
#[pyclass(frozen, get_all, module = "msl_core")]
#[derive(Clone, Debug)]
pub struct Symbol {
    name: String,
    kind: String,
    signature: String,
    lineno: usize,
    end_lineno: usize,
    parent: Option<String>,
    docstring: Option<String>,
    is_public: Option<bool>,
}

#[derive(Clone, Copy, PartialEq)]
enum Dialect {
    Python,
    JavaScript,
    TypeScript,
    Rust,
    Go,
    Cpp,
    Java,
}

fn language(path: &str) -> PyResult<(Dialect, Language)> {
    let extension = Path::new(path)
        .extension()
        .and_then(|value| value.to_str())
        .unwrap_or("")
        .to_ascii_lowercase();
    Ok(match extension.as_str() {
        "py" | "pyi" => (Dialect::Python, tree_sitter_python::LANGUAGE.into()),
        "js" | "jsx" | "mjs" | "cjs" => {
            (Dialect::JavaScript, tree_sitter_javascript::LANGUAGE.into())
        }
        "ts" | "mts" | "cts" => (
            Dialect::TypeScript,
            tree_sitter_typescript::LANGUAGE_TYPESCRIPT.into(),
        ),
        "tsx" => (
            Dialect::TypeScript,
            tree_sitter_typescript::LANGUAGE_TSX.into(),
        ),
        "rs" => (Dialect::Rust, tree_sitter_rust::LANGUAGE.into()),
        "go" => (Dialect::Go, tree_sitter_go::LANGUAGE.into()),
        "cpp" | "cc" | "cxx" | "h" | "hpp" | "hh" | "hxx" => {
            (Dialect::Cpp, tree_sitter_cpp::LANGUAGE.into())
        }
        "java" => (Dialect::Java, tree_sitter_java::LANGUAGE.into()),
        _ => {
            return Err(PyValueError::new_err(format!(
                "Unsupported source extension: {path}"
            )))
        }
    })
}

fn text<'a>(node: Node<'_>, code: &'a str) -> &'a str {
    &code[node.byte_range()]
}

fn last_line(node: Node<'_>) -> usize {
    let end = node.end_position();
    // Tree-sitter's end position is exclusive, possibly at the next line's start.
    end.row + usize::from(end.column != 0 || end.row == node.start_position().row)
}

#[derive(Clone)]
struct Scope {
    path: String,
    kind: &'static str,
}

struct Declaration<'a> {
    name: String,
    kind: &'static str,
    body: Option<Node<'a>>,
    parent: Option<String>,
}

// Follow declarator/type spines rather than accidentally selecting parameter names.
fn identifier(mut node: Node<'_>, code: &str) -> Option<String> {
    loop {
        match node.kind() {
            "identifier"
            | "type_identifier"
            | "field_identifier"
            | "property_identifier"
            | "private_property_identifier"
            | "destructor_name"
            | "operator_name" => {
                return Some(text(node, code).to_owned());
            }
            "qualified_identifier" | "scoped_type_identifier" => {
                return Some(text(node, code).to_owned())
            }
            _ => {
                node = node
                    .child_by_field_name("declarator")
                    .or_else(|| node.child_by_field_name("type"))
                    .or_else(|| node.child_by_field_name("name"))
                    .or_else(|| {
                        if matches!(node.kind(), "pointer_type" | "parenthesized_declarator") {
                            node.named_child(0)
                        } else {
                            None
                        }
                    })?;
            }
        }
    }
}

fn describe<'a>(
    node: Node<'a>,
    dialect: Dialect,
    code: &str,
    scope: Option<&Scope>,
) -> Option<Declaration<'a>> {
    let mut body = node.child_by_field_name("body");
    let mut name = node.child_by_field_name("name");
    let mut parent = None;
    let kind = match (dialect, node.kind()) {
        (Dialect::Python, "class_definition")
        | (
            Dialect::JavaScript | Dialect::TypeScript,
            "class_declaration" | "abstract_class_declaration",
        )
        | (Dialect::Java, "class_declaration")
        | (Dialect::Cpp, "class_specifier") => "class",
        (Dialect::Rust, "struct_item") | (Dialect::Cpp, "struct_specifier") => "struct",
        (Dialect::Python, "function_definition")
        | (Dialect::Rust, "function_item" | "function_signature_item") => {
            if scope.is_some_and(|scope| matches!(scope.kind, "class" | "struct")) {
                "method"
            } else {
                "function"
            }
        }
        (
            Dialect::JavaScript | Dialect::TypeScript,
            "function_declaration" | "generator_function_declaration" | "function_signature",
        )
        | (Dialect::Go, "function_declaration") => "function",
        (
            Dialect::JavaScript | Dialect::TypeScript,
            "method_definition" | "method_signature" | "abstract_method_signature",
        )
        | (Dialect::Java, "method_declaration" | "constructor_declaration") => "method",
        (Dialect::Go, "method_declaration") => {
            let receiver = node.child_by_field_name("receiver")?.named_child(0)?;
            parent = identifier(receiver.child_by_field_name("type")?, code);
            "method"
        }
        (Dialect::Go, "type_spec") => {
            let structure = node.child_by_field_name("type")?;
            if structure.kind() != "struct_type" {
                return None;
            }
            body = structure.named_child(0);
            "struct"
        }
        (Dialect::JavaScript | Dialect::TypeScript, "variable_declarator") => {
            let value = node.child_by_field_name("value")?;
            if !matches!(
                value.kind(),
                "arrow_function" | "function_expression" | "generator_function"
            ) {
                return None;
            }
            body = value.child_by_field_name("body");
            "function"
        }
        (Dialect::Cpp, "function_definition" | "declaration" | "field_declaration") => {
            let mut declarator = node.child_by_field_name("declarator")?;
            while matches!(
                declarator.kind(),
                "pointer_declarator" | "reference_declarator"
            ) {
                declarator = declarator
                    .child_by_field_name("declarator")
                    .or_else(|| declarator.named_child(0))?;
            }
            if declarator.kind() != "function_declarator" {
                return None;
            }
            name = declarator.child_by_field_name("declarator");
            if name.is_some_and(|name| name.kind() == "parenthesized_declarator") {
                return None;
            }
            if scope.is_some_and(|scope| matches!(scope.kind, "class" | "struct")) {
                "method"
            } else {
                "function"
            }
        }
        _ => return None,
    };
    // Forward class/struct declarations have no definition to outline.
    if matches!(kind, "class" | "struct") && body.is_none() && dialect != Dialect::Rust {
        return None;
    }
    Some(Declaration {
        name: identifier(name?, code)?,
        kind,
        body,
        parent,
    })
}

fn summary(value: &str) -> Option<String> {
    let lines: Vec<_> = value
        .lines()
        .map(str::trim)
        .filter(|line| !line.is_empty())
        .collect();
    if lines.is_empty() {
        return None;
    }
    let mut result = lines.iter().take(2).copied().collect::<Vec<_>>().join(" ");
    if lines.len() > 2 {
        result.push_str("...");
    }
    Some(result)
}

fn documentation(
    node: Node<'_>,
    body: Option<Node<'_>>,
    dialect: Dialect,
    code: &str,
) -> Option<String> {
    if dialect == Dialect::Python {
        let body = body?;
        let mut cursor = body.walk();
        let statement = body
            .named_children(&mut cursor)
            .find(|node| node.kind() != "comment")?;
        if statement.kind() != "expression_statement" {
            return None;
        }
        let literal = statement.named_child(0)?;
        if literal.kind() != "string" {
            return None;
        }
        let source = text(literal, code);
        let quote = source.find(['\'', '"'])?;
        if source[..quote]
            .chars()
            .any(|value| matches!(value, 'b' | 'B' | 'f' | 'F'))
        {
            return None;
        }
        let delimiter =
            if source[quote..].starts_with("\"\"\"") || source[quote..].starts_with("'''") {
                3
            } else {
                1
            };
        return summary(&source[quote + delimiter..source.len() - delimiter]);
    }
    let mut comments = Vec::new();
    let mut current = node;
    while let Some(previous) = current.prev_named_sibling() {
        if last_line(previous) < current.start_position().row {
            break;
        }
        if dialect == Dialect::Rust && previous.kind() == "attribute_item" {
            current = previous;
            continue;
        }
        let raw = text(previous, code).trim();
        if !matches!(
            previous.kind(),
            "comment" | "line_comment" | "block_comment"
        ) {
            break;
        }
        let content = if let Some(content) = raw.strip_prefix("/**") {
            content.strip_suffix("*/").unwrap_or(content)
        } else if let Some(content) = raw.strip_prefix("///") {
            content
        } else if dialect == Dialect::Go {
            raw.strip_prefix("//")
                .or_else(|| raw.strip_prefix("/*")?.strip_suffix("*/"))?
        } else {
            break;
        };
        comments.push(
            content
                .lines()
                .map(|line| line.trim().trim_start_matches('*').trim())
                .collect::<Vec<_>>()
                .join("\n"),
        );
        current = previous;
    }
    comments.reverse();
    summary(&comments.join("\n"))
}

fn cpp_access(node: Node<'_>, code: &str) -> Option<bool> {
    let mut entry = node;
    while let Some(parent) = entry.parent() {
        if parent.kind() == "field_declaration_list" {
            let owner = parent.parent()?;
            let mut public = owner.kind() == "struct_specifier";
            let mut cursor = parent.walk();
            for sibling in parent.named_children(&mut cursor) {
                if sibling.id() == entry.id() {
                    return Some(public);
                }
                if sibling.kind() == "access_specifier" {
                    public = text(sibling, code) == "public";
                }
            }
        }
        if parent.kind() == "function_definition" {
            break;
        }
        entry = parent;
    }
    None
}

fn public(
    node: Node<'_>,
    anchor: Node<'_>,
    name: &str,
    dialect: Dialect,
    code: &str,
) -> Option<bool> {
    let mut cursor = node.walk();
    let children: Vec<_> = node.named_children(&mut cursor).collect();
    match dialect {
        Dialect::Python => None,
        Dialect::Go => Some(name.chars().next().is_some_and(char::is_uppercase)),
        Dialect::Rust => Some(
            children
                .iter()
                .any(|child| child.kind() == "visibility_modifier" && text(*child, code) == "pub"),
        ),
        Dialect::Cpp => cpp_access(node, code),
        Dialect::Java => Some(
            children
                .iter()
                .filter(|child| child.kind() == "modifiers")
                .any(|child| {
                    text(*child, code)
                        .split_whitespace()
                        .any(|word| word == "public")
                }),
        ),
        Dialect::JavaScript | Dialect::TypeScript => {
            let declaration = node.parent().filter(|parent| {
                matches!(
                    parent.kind(),
                    "lexical_declaration" | "variable_declaration"
                )
            });
            if anchor.kind() == "export_statement"
                || declaration
                    .and_then(|node| node.parent())
                    .is_some_and(|node| node.kind() == "export_statement")
            {
                return Some(true);
            }
            if name.starts_with('#') {
                return Some(false);
            }
            children
                .iter()
                .find(|child| child.kind() == "accessibility_modifier")
                .map(|child| text(*child, code) == "public")
        }
    }
}

fn extract(path: &str, code: &str) -> PyResult<Vec<Symbol>> {
    let (dialect, language) = language(path)?;
    let mut parser = Parser::new();
    parser
        .set_language(&language)
        .map_err(|error| PyRuntimeError::new_err(error.to_string()))?;
    parser.set_timeout_micros(1_000_000);
    let tree = parser
        .parse(code, None)
        .ok_or_else(|| PyRuntimeError::new_err("AST parsing timed out or was cancelled"))?;
    let root = tree.root_node();
    if root.has_error() {
        let mut pending = vec![root];
        let mut invalid = root;
        while let Some(node) = pending.pop() {
            if node.is_error() || node.is_missing() {
                invalid = node;
                break;
            }
            for index in (0..node.child_count()).rev() {
                if let Some(child) = node.child(index) {
                    pending.push(child);
                }
            }
        }
        let point = invalid.start_position();
        let line = code.lines().nth(point.row).unwrap_or("");
        let column = line
            .get(..point.column)
            .map_or(1, |prefix| prefix.chars().count() + 1);
        return Err(PySyntaxError::new_err((
            "Tree-sitter reported an error or missing syntax; no symbols returned",
            (path.to_owned(), point.row + 1, column, line.to_owned()),
        )));
    }
    let mut result = Vec::new();
    let mut pending = vec![(root, None::<Scope>)];
    while let Some((node, mut scope)) = pending.pop() {
        if matches!(
            node.kind(),
            "trait_item"
                | "enum_item"
                | "interface_declaration"
                | "enum_declaration"
                | "annotation_type_declaration"
                | "record_declaration"
        ) {
            continue; // Unsupported containers must not produce unowned methods.
        }
        if dialect == Dialect::Rust && node.kind() == "impl_item" {
            if let Some(owner) = node
                .child_by_field_name("type")
                .and_then(|node| identifier(node, code))
            {
                scope = Some(Scope {
                    path: owner.replace("::", "."),
                    kind: "struct",
                });
            }
        }
        if let Some(declaration) = describe(node, dialect, code, scope.as_ref()) {
            let parent = declaration
                .parent
                .or_else(|| scope.as_ref().map(|scope| scope.path.clone()));
            let qualified = parent.as_ref().map_or_else(
                || declaration.name.clone(),
                |parent| format!("{parent}.{}", declaration.name),
            );
            let mut anchor = node;
            if matches!(node.kind(), "variable_declarator" | "type_spec") {
                if let Some(container) = node.parent() {
                    let mut cursor = container.walk();
                    if container
                        .named_children(&mut cursor)
                        .filter(|child| child.kind() == node.kind())
                        .count()
                        == 1
                    {
                        anchor = container;
                    }
                }
            }
            anchor = anchor
                .parent()
                .filter(|parent| parent.kind() == "export_statement")
                .unwrap_or(anchor);
            let end = declaration
                .body
                .map_or(node.end_byte(), |body| body.start_byte());
            result.push((
                node.start_byte(),
                Symbol {
                    is_public: public(node, anchor, &declaration.name, dialect, code),
                    docstring: documentation(anchor, declaration.body, dialect, code),
                    name: declaration.name,
                    kind: declaration.kind.to_owned(),
                    signature: code[anchor.start_byte()..end].trim().to_owned(),
                    lineno: anchor.start_position().row + 1,
                    end_lineno: last_line(anchor),
                    parent,
                },
            ));
            if let Some(body) = declaration.body {
                pending.push((
                    body,
                    Some(Scope {
                        path: qualified,
                        kind: declaration.kind,
                    }),
                ));
            }
            continue;
        }
        for index in (0..node.named_child_count()).rev() {
            if let Some(child) = node.named_child(index) {
                pending.push((child, scope.clone()));
            }
        }
    }
    if dialect == Dialect::Cpp {
        let owners: HashSet<_> = result
            .iter()
            .map(|(_, symbol)| symbol)
            .filter(|symbol| matches!(symbol.kind.as_str(), "class" | "struct"))
            .map(|symbol| {
                symbol.parent.as_ref().map_or_else(
                    || symbol.name.clone(),
                    |parent| format!("{parent}.{}", symbol.name),
                )
            })
            .collect();
        for (_, symbol) in &mut result {
            if symbol.kind != "function" {
                continue;
            }
            if let Some((owner, name)) = symbol.name.rsplit_once("::") {
                if owners.contains(&owner.replace("::", ".")) {
                    symbol.parent = Some(owner.replace("::", "."));
                    symbol.name = name.to_owned();
                    symbol.kind = "method".into();
                }
            }
        }
    }
    // Keep byte offsets internal so same-line declarations retain source order.
    result.sort_by_key(|(start_byte, _)| *start_byte);
    Ok(result.into_iter().map(|(_, symbol)| symbol).collect())
}

/// Extract a syntax-only outline from supplied source; the path selects a grammar.
#[pyfunction]
pub fn extract_ast_symbols(py: Python<'_>, file_path: &str, code: &str) -> PyResult<Vec<Symbol>> {
    py.detach(|| extract(file_path, code))
}
