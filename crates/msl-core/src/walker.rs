//! Project-local, parallel discovery of text files. This is not kit.source_files.

use ignore::gitignore::GitignoreBuilder;
use ignore::{WalkBuilder, WalkState};
use pyo3::exceptions::{PyOSError, PyValueError};
use pyo3::prelude::*;
use std::fs::{self, File};
use std::io::{self, Read};
use std::path::{Component, Path, PathBuf};
use std::sync::{Arc, Mutex};

const SAMPLE_BYTES: u64 = 8192;

enum WalkError {
    Invalid(String),
    Io(String),
}

impl From<io::Error> for WalkError {
    fn from(error: io::Error) -> Self {
        Self::Io(error.to_string())
    }
}

#[derive(Default)]
struct Results {
    paths: Vec<String>,
    error: Option<WalkError>,
}

fn fail(results: &Mutex<Results>, error: WalkError) {
    let mut results = results.lock().unwrap_or_else(|error| error.into_inner());
    if results.error.is_none() {
        results.error = Some(error);
    }
}

// ignore opens rule files itself. Check them before it enters each directory,
// including the root, so a symlink cannot be used as an ignore-file source.
fn check_rule_files(directory: &Path) -> Result<(), WalkError> {
    for name in [".gitignore", ".mklignore"] {
        let path = directory.join(name);
        match fs::symlink_metadata(&path) {
            Ok(metadata) => {
                if !metadata.is_file() || metadata.file_type().is_symlink() {
                    return Err(WalkError::Io(format!(
                        "Ignore file must be a regular non-symlink file: {}",
                        path.display()
                    )));
                }
                File::open(&path).map_err(|error| {
                    WalkError::Io(format!("Cannot read {}: {error}", path.display()))
                })?;
            }
            Err(error) if error.kind() == io::ErrorKind::NotFound => {}
            Err(error) => return Err(WalkError::Io(format!("{}: {error}", path.display()))),
        }
    }
    Ok(())
}

fn relative_posix(root: &Path, path: &Path) -> Result<String, WalkError> {
    let relative = path
        .strip_prefix(root)
        .map_err(|_| WalkError::Io(format!("Entry outside project root: {}", path.display())))?;
    let mut parts = Vec::new();
    for component in relative.components() {
        match component {
            Component::Normal(part) => parts.push(part.to_str().ok_or_else(|| {
                WalkError::Invalid(format!("Path is not UTF-8: {}", path.display()))
            })?),
            _ => return Err(WalkError::Invalid("Invalid relative path".into())),
        }
    }
    Ok(parts.join("/"))
}

fn is_text(path: &Path) -> Result<bool, WalkError> {
    // Recheck the entry before opening; callers must keep the tree stable during
    // a walk. This API is not a sandbox against concurrent filesystem mutation.
    let metadata = fs::symlink_metadata(path)?;
    if !metadata.is_file() || metadata.file_type().is_symlink() {
        return Ok(false);
    }
    let mut sample = Vec::new();
    File::open(path)?
        .take(SAMPLE_BYTES)
        .read_to_end(&mut sample)?;
    if sample.contains(&0) {
        return Ok(false);
    }
    Ok(match std::str::from_utf8(&sample) {
        Ok(_) => true,
        // A UTF-8 character may straddle the sample boundary.
        Err(error) => error.error_len().is_none() && metadata.len() > sample.len() as u64,
    })
}

fn walk(root: String, patterns: Vec<String>) -> Result<Vec<String>, WalkError> {
    if root.is_empty() {
        return Err(WalkError::Invalid("Project root must not be empty".into()));
    }
    let root: PathBuf = Path::new(&root).components().collect();
    let mut prefix = PathBuf::new();
    for component in root.components() {
        prefix.push(component);
        if fs::symlink_metadata(&prefix)?.file_type().is_symlink() {
            return Err(WalkError::Io(
                "Project root must not contain symlink components".into(),
            ));
        }
    }
    let metadata = fs::symlink_metadata(&root)?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err(WalkError::Io(
            "Project root must be a non-symlink directory".into(),
        ));
    }
    let root = root.canonicalize()?;
    check_rule_files(&root)?;
    let mut extra = GitignoreBuilder::new(&root);
    for pattern in patterns {
        if pattern.contains(['\n', '\r', '\0']) {
            return Err(WalkError::Invalid(
                "Each ignore pattern must be a single line".into(),
            ));
        }
        extra
            .add_line(None, &pattern)
            .map_err(|error| WalkError::Invalid(format!("Invalid ignore pattern: {error}")))?;
    }
    let extra = extra
        .build()
        .map_err(|error| WalkError::Invalid(format!("Invalid ignore patterns: {error}")))?;
    let results = Arc::new(Mutex::new(Results::default()));
    let mut builder = WalkBuilder::new(&root);
    builder
        .follow_links(false)
        .hidden(false)
        .parents(false)
        .ignore(false)
        .git_global(false)
        .git_exclude(false)
        .git_ignore(true)
        .require_git(false)
        .threads(std::thread::available_parallelism().map_or(2, |count| count.get().clamp(2, 8)))
        .add_custom_ignore_filename(".mklignore");
    // The filter runs before descending and before loading child ignore files.
    // Extra rules can narrow the result but cannot resurrect ignored parents.
    let filter_results = Arc::clone(&results);
    builder.filter_entry(move |entry| {
        if entry.file_name() == ".git" || entry.path_is_symlink() {
            return false;
        }
        let is_dir = entry.file_type().is_some_and(|kind| kind.is_dir());
        if extra
            .matched_path_or_any_parents(entry.path(), is_dir)
            .is_ignore()
        {
            return false;
        }
        if is_dir {
            if let Err(error) = check_rule_files(entry.path()) {
                fail(&filter_results, error);
                return false;
            }
        }
        true
    });
    builder.build_parallel().run(|| {
        Box::new(|entry| {
            let result = (|| {
                let entry = entry.map_err(|error| WalkError::Io(error.to_string()))?;
                if let Some(error) = entry.error() {
                    return Err(WalkError::Io(error.to_string()));
                }
                if entry.path_is_symlink() || !entry.file_type().is_some_and(|kind| kind.is_file())
                {
                    return Ok(None);
                }
                let path = relative_posix(&root, entry.path())?;
                if is_text(entry.path())? {
                    Ok(Some(path))
                } else {
                    Ok(None)
                }
            })();
            match result {
                Ok(path) => {
                    let mut results = results.lock().unwrap_or_else(|error| error.into_inner());
                    if results.error.is_some() {
                        return WalkState::Quit;
                    }
                    if let Some(path) = path {
                        results.paths.push(path);
                    }
                    WalkState::Continue
                }
                Err(error) => {
                    fail(&results, error);
                    WalkState::Quit
                }
            }
        })
    });
    let mut guard = results.lock().unwrap_or_else(|error| error.into_inner());
    let results = std::mem::take(&mut *guard);
    if let Some(error) = results.error {
        return Err(error);
    }
    let mut paths = results.paths;
    paths.sort_unstable();
    paths.dedup();
    Ok(paths)
}

/// Return sorted, relative POSIX paths of project-local UTF-8 text candidates.
#[pyfunction]
pub fn walk_project(
    py: Python<'_>,
    root: String,
    ignore_patterns: Vec<String>,
) -> PyResult<Vec<String>> {
    py.detach(move || walk(root, ignore_patterns))
        .map_err(|error| match error {
            WalkError::Invalid(message) => PyValueError::new_err(message),
            WalkError::Io(message) => PyOSError::new_err(message),
        })
}
