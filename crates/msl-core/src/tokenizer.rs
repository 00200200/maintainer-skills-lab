//! Exact base encodings with Python tiktoken's default special-token policy.

use pyo3::create_exception;
use pyo3::exceptions::{PyRuntimeError, PyUnicodeEncodeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyString;
use std::sync::OnceLock;
use tiktoken_rs::{cl100k_base, o200k_base, CoreBPE};

create_exception!(msl_core, DisallowedSpecialTokenError, PyValueError);

static CL100K: OnceLock<Result<CoreBPE, String>> = OnceLock::new();
static O200K: OnceLock<Result<CoreBPE, String>> = OnceLock::new();

fn count(text: &str, encoding: &str) -> PyResult<usize> {
    let (cache, specials): (_, &[&str]) = match encoding {
        "cl100k_base" => (
            &CL100K,
            &[
                "<|endoftext|>",
                "<|fim_prefix|>",
                "<|fim_middle|>",
                "<|fim_suffix|>",
                "<|endofprompt|>",
            ],
        ),
        "o200k_base" => (&O200K, &["<|endoftext|>", "<|endofprompt|>"]),
        _ => {
            return Err(PyValueError::new_err(format!(
                "Unknown encoding {encoding}"
            )))
        }
    };
    // Do not silently encode known special spellings as ordinary text, or count
    // them as allowed tokens: Encoding.encode() rejects them by default.
    if let Some(special) = specials.iter().find(|special| text.contains(**special)) {
        return Err(DisallowedSpecialTokenError::new_err(format!(
            "Encountered text corresponding to disallowed special token {special:?}"
        )));
    }
    if text.is_empty() {
        return Ok(0);
    }
    let bpe = cache.get_or_init(|| {
        let initialized = if encoding == "cl100k_base" {
            cl100k_base()
        } else {
            o200k_base()
        };
        initialized.map_err(|error| error.to_string())
    });
    let bpe = bpe.as_ref().map_err(|error| {
        PyRuntimeError::new_err(format!("Cannot initialize {encoding}: {error}"))
    })?;
    Ok(bpe.encode_ordinary(text).len())
}

/// Count tokens like tiktoken.get_encoding(encoding).encode(text), with defaults.
#[pyfunction(signature = (text, encoding = "cl100k_base"))]
pub fn count_tokens(text: &Bound<'_, PyString>, encoding: &str) -> PyResult<usize> {
    let py = text.py();
    let normalized = match text.extract::<String>() {
        Ok(text) => text,
        Err(error) if error.is_instance_of::<PyUnicodeEncodeError>(py) => {
            // Match Python tiktoken: combine surrogate pairs and replace lone
            // surrogates using Python's codec semantics, without normalization.
            text.call_method1("encode", ("utf-16", "surrogatepass"))?
                .call_method1("decode", ("utf-16", "replace"))?
                .extract::<String>()?
        }
        Err(error) => return Err(error),
    };
    py.detach(|| count(&normalized, encoding))
}
