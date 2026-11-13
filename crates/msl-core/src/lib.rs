//! A literal port of kit.py's minifier, not a Markdown parser or an AST rewrite.

use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyString};

mod symbols;
mod tokenizer;
mod walker;

// All buffers are Python UTF-8 with surrogatepass. Keeping bytes lets us round-trip
// lone Python surrogates without unsafe code or conversion to Rust Unicode scalars.
fn codepoint(bytes: &[u8], start: usize) -> (u32, usize) {
    let first = bytes[start];
    let (mut value, width) = match first {
        0x00..=0x7f => return (u32::from(first), 1),
        0xc0..=0xdf => (u32::from(first & 0x1f), 2),
        0xe0..=0xef => (u32::from(first & 0x0f), 3),
        _ => (u32::from(first & 0x07), 4),
    };
    for byte in &bytes[start + 1..start + width] {
        value = (value << 6) | u32::from(byte & 0x3f);
    }
    (value, width)
}

fn python_whitespace(value: u32) -> bool {
    // Python str.strip() includes U+001C..U+001F, unlike Rust's whitespace predicate.
    matches!(value, 0x09..=0x0d | 0x1c..=0x20 | 0x85 | 0xa0 | 0x1680 |
        0x2000..=0x200a | 0x2028 | 0x2029 | 0x202f | 0x205f | 0x3000)
}

fn strip_python(bytes: &[u8]) -> &[u8] {
    let mut start = 0;
    let mut end = bytes.len();
    while start < end {
        let (value, width) = codepoint(bytes, start);
        if !python_whitespace(value) {
            break;
        }
        start += width;
    }
    while start < end {
        let mut previous = end - 1;
        while bytes[previous] & 0xc0 == 0x80 {
            previous -= 1;
        }
        if !python_whitespace(codepoint(bytes, previous).0) {
            break;
        }
        end = previous;
    }
    &bytes[start..end]
}

fn horizontal_space(byte: u8) -> bool {
    byte == b' ' || byte == b'\t'
}

fn compact_table_line(line: &[u8]) -> Vec<u8> {
    let stripped = strip_python(line);
    if stripped.first() != Some(&b'|') || stripped.len() < 2 || stripped.last() != Some(&b'|') {
        let end = line
            .iter()
            .rposition(|byte| !horizontal_space(*byte))
            .map_or(0, |index| index + 1);
        return line[..end].to_vec();
    }
    let lead = line
        .iter()
        .take_while(|byte| horizontal_space(**byte))
        .count();
    let mut output = line[..lead].to_vec();
    output.extend_from_slice(b"| ");
    for (index, cell) in stripped[1..stripped.len() - 1]
        .split(|byte| *byte == b'|')
        .enumerate()
    {
        if index > 0 {
            output.extend_from_slice(b" | ");
        }
        output.extend_from_slice(strip_python(cell));
    }
    output.extend_from_slice(b" |");
    output
}

fn find(bytes: &[u8], needle: &[u8]) -> Option<usize> {
    bytes
        .windows(needle.len())
        .position(|window| window == needle)
}

fn minify_segment(text: &[u8]) -> Vec<u8> {
    let mut uncommented = Vec::with_capacity(text.len());
    let mut cursor = 0;
    while let Some(relative) = find(&text[cursor..], b"<!--") {
        let start = cursor + relative;
        let Some(close) = find(&text[start + 4..], b"-->") else {
            break; // An unclosed comment remains literal, as in Python's regex.
        };
        uncommented.extend_from_slice(&text[cursor..start]);
        cursor = start + 4 + close + 3;
    }
    uncommented.extend_from_slice(&text[cursor..]);
    let mut joined = Vec::with_capacity(uncommented.len());
    for (index, line) in uncommented.split(|byte| *byte == b'\n').enumerate() {
        if index > 0 {
            joined.push(b'\n');
        }
        joined.extend_from_slice(&compact_table_line(line));
    }
    let mut output = Vec::with_capacity(joined.len());
    let mut newlines = 0;
    for byte in joined {
        if byte == b'\n' {
            newlines += 1;
            if newlines > 2 {
                continue;
            }
        } else {
            newlines = 0;
        }
        output.push(byte);
    }
    output
}

fn fence_prefix(line: &[u8]) -> Option<(u8, usize, usize)> {
    let indent = line.iter().take_while(|byte| **byte == b' ').count();
    if indent > 3 {
        return None;
    }
    let marker = *line.get(indent)?;
    if marker != b'`' && marker != b'~' {
        return None;
    }
    let length = line[indent..]
        .iter()
        .take_while(|byte| **byte == marker)
        .count();
    if length < 3 {
        return None;
    }
    Some((marker, length, indent + length))
}

fn minify_bytes(text: &[u8]) -> Vec<u8> {
    // split(), not lines(): CR and the final empty line must be preserved.
    let lines: Vec<&[u8]> = text.split(|byte| *byte == b'\n').collect();
    let mut offsets = Vec::with_capacity(lines.len());
    let mut position = 0;
    for line in &lines {
        offsets.push(position);
        position += line.len() + 1;
    }
    let mut spans = Vec::new();
    let mut index = 0;
    while index < lines.len() {
        let Some((marker, length, _)) = fence_prefix(lines[index]) else {
            index += 1;
            continue;
        };
        let start = index;
        index += 1;
        let mut end = text.len();
        while index < lines.len() {
            if let Some((closing_marker, closing_length, suffix)) = fence_prefix(lines[index]) {
                if closing_marker == marker
                    && closing_length >= length
                    && lines[index][suffix..]
                        .iter()
                        .all(|byte| horizontal_space(*byte))
                {
                    end = offsets[index] + lines[index].len();
                    index += 1;
                    break;
                }
            }
            index += 1;
        }
        spans.push((offsets[start], end));
    }
    if spans.is_empty() {
        return minify_segment(text);
    }
    let mut protected = Vec::with_capacity(text.len());
    let mut cursor = 0;
    for (index, &(start, end)) in spans.iter().enumerate() {
        protected.extend_from_slice(&text[cursor..start]);
        protected.extend_from_slice(format!("@@FENCE{index}@@").as_bytes());
        cursor = end;
    }
    protected.extend_from_slice(&text[cursor..]);
    let mut output = minify_segment(&protected);
    // Preserve Python's first-occurrence replacement, including literal-token collisions.
    for (index, &(start, end)) in spans.iter().enumerate() {
        let token = format!("@@FENCE{index}@@");
        if let Some(location) = find(&output, token.as_bytes()) {
            output.splice(
                location..location + token.len(),
                text[start..end].iter().copied(),
            );
        }
    }
    output
}

/// Shrink Markdown with the same rules as tools.kit.minify_markdown.
#[pyfunction]
fn minify_markdown<'py>(text: &Bound<'py, PyString>) -> PyResult<Bound<'py, PyString>> {
    let encoded = text.call_method1("encode", ("utf-8", "surrogatepass"))?;
    let bytes = encoded.cast::<PyBytes>()?;
    let output = minify_bytes(bytes.as_bytes());
    let decoded =
        PyBytes::new(text.py(), &output).call_method1("decode", ("utf-8", "surrogatepass"))?;
    Ok(decoded.cast_into::<PyString>()?)
}

/// Hash exact bytes with BLAKE3 and return a 64-character lowercase hex digest.
#[pyfunction]
fn blake3_hash(data: &Bound<'_, PyBytes>) -> String {
    let bytes = data.as_bytes();
    data.py()
        .detach(|| blake3::hash(bytes).to_hex().to_string())
}

#[pymodule]
fn msl_core(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(blake3_hash, module)?)?;
    module.add_function(wrap_pyfunction!(minify_markdown, module)?)?;
    module.add_function(wrap_pyfunction!(walker::walk_project, module)?)?;
    module.add_function(wrap_pyfunction!(tokenizer::count_tokens, module)?)?;
    module.add_class::<symbols::Symbol>()?;
    module.add_function(wrap_pyfunction!(symbols::extract_ast_symbols, module)?)?;
    module.add(
        "DisallowedSpecialTokenError",
        module
            .py()
            .get_type::<tokenizer::DisallowedSpecialTokenError>(),
    )?;
    module.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
