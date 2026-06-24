"""
Planning Compiler — Pre-Runtime Deterministic Plan Repair

Complies with PLANNING_COMPILER_CONTRACT_V1:
  - Receives planner output (candidate structure, not trusted)
  - Applies deterministic repairs within narrow rules
  - Hands verified plan to workflow_validator as fail-safe
  - Does NOT execute tools, mutate lifecycle, or bypass governance

Current scope:
  - ISSUE-PDIAG-002B: Final/all-prior/multi-source synthesis dependency auto-binding
"""

from system.orchestrator.synthesis_dependency_utils import (
    _get_required_synthesis_dependencies,
    _is_all_prior_synthesis_step,
    _is_synthesis_step,
)


def apply_synthesis_dependency_binding(workflow: dict) -> dict:
    """
    Deterministically repair missing dependencies for existing all-prior synthesis steps.

    Rules:
      1. Only operates on steps already identified as all-prior synthesis.
      2. Only binds prior non-synthesis source steps.
      3. Preserves existing valid dependencies.
      4. Does NOT create new steps.
      5. Does NOT modify targeted synthesis (explicit single references).
      6. Does NOT bind future steps or self.
      7. Idempotent: running twice produces the same result.

    Args:
        workflow: workflow dict with "steps" list

    Returns:
        Repaired workflow dict (mutates in place for efficiency, but conceptually pure).
    """
    steps = workflow.get("steps", [])
    if not isinstance(steps, list) or len(steps) <= 1:
        return workflow

    total_steps = len(steps)

    for i, step in enumerate(steps):
        if not _is_all_prior_synthesis_step(step, i, total_steps):
            continue

        step_id = step.get("id")
        if not step_id:
            continue

        required = _get_required_synthesis_dependencies(steps, i)
        if not required:
            continue

        declared = step.get("depends_on", []) or []
        if not isinstance(declared, list):
            declared = []

        # Preserve existing order, append missing deterministically
        missing = [dep for dep in sorted(required) if dep not in declared]
        if missing:
            step["depends_on"] = declared + missing

    return workflow


def _restore_resource_references_in_purpose(purpose: str, resource: str, resource_type: str) -> str:
    """
    Append a concrete resource reference to a step purpose if it is missing.

    Args:
        purpose: current step purpose text
        resource: normalized resource identifier (path or URL)
        resource_type: "path" or "url"

    Returns:
        purpose with the resource reference restored naturally
    """
    if resource_type == "url":
        return f"{purpose} at {resource}"
    return f"{purpose} in {resource}"


_RESOURCE_OPERATION_MARKERS = frozenset([
    "read", "write", "edit", "fetch", "get", "search", "load", "open",
    "save", "create", "post", "put", "delete", "download", "upload",
])


def _is_synthesis_only_step(step: dict) -> bool:
    """
    Return True if a step is a pure synthesis/final-answer step and not a
    resource-access or resource-mutation operation.

    A synthesis step consumes prior outputs (e.g., summarize, compare, report,
    explain) and should not have concrete resource paths/URLs restored onto it.
    """
    purpose = step.get("purpose", "")
    expected_outcome = step.get("expected_outcome", "")
    if not _is_synthesis_step(purpose, expected_outcome):
        return False
    text = (purpose + " " + expected_outcome).lower()
    return not any(marker in text for marker in _RESOURCE_OPERATION_MARKERS)


def apply_resource_reference_restoration(workflow: dict) -> dict:
    """
    Deterministic post-planner repair that restores concrete resource references
    in dependent resource-access or consumer steps when the planner output lost them.

    Rules:
      1. Only operates on steps already in the plan.
      2. Only restores resources that are present in an explicitly-declared
         prior dependency and are missing from the current step purpose.
      3. Only restores references for steps that are genuine resource operations
         (read/write/edit/fetch/search) or resource consumers that are NOT
         pure synthesis/final-answer steps.
      4. Does NOT create new steps, delete steps, or modify agent selection.
      5. Idempotent: running twice produces the same result.
    """
    steps = workflow.get("steps", [])
    if not isinstance(steps, list) or len(steps) <= 1:
        return workflow

    # Pre-compute resources for each step
    step_resources: dict[str, set[tuple[str, str]]] = {}
    for step in steps:
        step_id = step.get("id")
        if not step_id:
            continue
        text = (step.get("purpose", "") + " " + step.get("expected_outcome", "")).strip()
        resources: set[tuple[str, str]] = set()
        for path in _extract_local_file_paths(text):
            norm = _normalize_local_file_path(path)
            if norm:
                resources.add(("path", norm))
        for url in _extract_urls(text):
            norm = _normalize_url(url)
            if norm:
                resources.add(("url", norm))
        step_resources[step_id] = resources

    for step in steps:
        step_id = step.get("id")
        if not step_id:
            continue

        purpose = step.get("purpose", "")
        if not purpose:
            continue

        # Do not restore resource references onto pure synthesis/final-answer steps.
        # Synthesis steps consume prior outputs and should not be re-anchored to
        # the original concrete resource, which would imply a new read/fetch/edit.
        if _is_synthesis_only_step(step):
            continue

        # Collect resources from declared dependencies and restore missing ones.
        # This is safe because the dependency is explicit: if step N depends on
        # step M and step M operated on a concrete resource, step N's purpose
        # should reference that resource so the executor knows what to operate on.
        for dep_id in step.get("depends_on", []) or []:
            for rtype, resource in step_resources.get(dep_id, set()):
                if rtype == "path":
                    current_paths = {_normalize_local_file_path(p) for p in _extract_local_file_paths(purpose)}
                    # Treat an absolute path that ends with the relative dependency path as a match,
                    # e.g. C:/temp/tmp/file.txt is equivalent to tmp/file.txt for our purposes.
                    if resource not in current_paths and not any(
                        cp and cp.endswith(resource) for cp in current_paths
                    ):
                        purpose = _restore_resource_references_in_purpose(purpose, resource, "path")
                elif rtype == "url":
                    current_urls = {_normalize_url(u) for u in _extract_urls(purpose)}
                    if resource not in current_urls:
                        purpose = _restore_resource_references_in_purpose(purpose, resource, "url")

        step["purpose"] = purpose

    return workflow


def apply_edit_step_path_repair(workflow: dict, user_input: str | None = None) -> dict:
    """
    Deterministic fallback for the common planner failure where an edit/update
    step is emitted without a concrete file path.

    If an edit step has no path and the immediately preceding relevant step is
    a read on exactly one file path, this repair:
      1. restores that path into the edit step's purpose, and
      2. adds a dependency from the edit step to the prior read step.

    Rules:
      - Only applies to file operations (not web URLs).
      - Only applies when the edit step has no own path or URL.
      - Only applies when the prior step is classified as read and has exactly
        one file path.
      - Only applies when the user_input contains sequencing markers such as
        "then", "after reading", "after read", or "read first".
      - Does not create steps or modify agent selection.
    """
    steps = workflow.get("steps", [])
    if not isinstance(steps, list) or len(steps) < 2:
        return workflow

    # Pre-compute metadata
    step_meta: dict[str, dict] = {}
    for step in steps:
        step_id = step.get("id")
        if not step_id:
            continue
        text = (step.get("purpose", "") + " " + step.get("expected_outcome", "")).strip()
        paths = set()
        for path in _extract_local_file_paths(text):
            norm = _normalize_local_file_path(path)
            if norm:
                paths.add(norm)
        urls = set()
        for url in _extract_urls(text):
            norm = _normalize_url(url)
            if norm:
                urls.add(norm)
        file_op = _classify_file_operation(step)
        web_op = _classify_web_operation(step)
        op = web_op if web_op != "unknown" else file_op
        step_meta[step_id] = {
            "paths": paths,
            "urls": urls,
            "op": op,
        }

    # No user input means no sequencing signal
    if not user_input:
        return workflow
    ui = user_input.lower()
    if not any(marker in ui for marker in _SEQUENCE_MARKERS):
        return workflow

    for i, step in enumerate(steps):
        step_id = step.get("id")
        if not step_id:
            continue
        meta = step_meta.get(step_id)
        if not meta:
            continue
        # Only edit operations with no own resource reference
        if meta["op"] != "edit" or meta["paths"] or meta["urls"]:
            continue

        # Find the nearest prior step that is a read on exactly one file path
        prior_step = None
        prior_path = None
        for j in range(i - 1, -1, -1):
            prev = steps[j]
            prev_id = prev.get("id")
            if not prev_id:
                continue
            prev_meta = step_meta.get(prev_id)
            if not prev_meta:
                continue
            if prev_meta["op"] != "read" or prev_meta["urls"] or len(prev_meta["paths"]) != 1:
                continue
            prior_step = prev
            prior_path = next(iter(prev_meta["paths"]))
            break

        if not prior_step or not prior_path:
            continue

        # Restore the path into the purpose and add the dependency
        purpose = step.get("purpose", "")
        if purpose:
            step["purpose"] = _restore_resource_references_in_purpose(purpose, prior_path, "path")
        _add_dependency_if_missing(step, prior_step["id"])

    return workflow


# === ISSUE-PDIAG-006-RS1: Same-Resource Sequencing Safety ===

import re

_WRITE_MARKERS = frozenset([
    "write", "write to", "save", "save to", "create", "create file",
    "output to", "export to", "append", "append to",
])

_READ_MARKERS = frozenset([
    "read", "load", "open", "display", "show", "fetch", "get contents",
])

_EDIT_MARKERS = frozenset([
    "edit", "modify", "update", "replace", "change",
])

_SEQUENCE_MARKERS = frozenset([
    "then", "after reading", "after read", "read it first", "read first",
])

_WEB_READ_MARKERS = frozenset([
    "read_webpage", "read webpage", "read the webpage", "read https", "read url",
    "fetch webpage", "fetch https", "fetch url", "read website", "read the website",
])

_WEB_WRITE_MARKERS = frozenset([
    "write to https", "save to https", "post to https",
])

_WEB_EDIT_MARKERS = frozenset([
    "edit webpage", "update webpage", "modify webpage",
])

# Match Windows absolute paths, optionally preceded by a quote/bracket.
# Negative lookbehind prevents matching drive-letter-like fragments inside URLs (e.g. s:/ in https://).
# Captures the broad path string; trailing punctuation is stripped during normalization.
# Match Windows absolute paths, optionally preceded by a quote/bracket.
# Negative lookbehind prevents matching drive-letter-like fragments inside URLs (e.g. s:/ in https://).
# Captures the broad path string; trailing punctuation is stripped during normalization.
_PATH_RE = re.compile(
    r'(?i)(?<![\w])(?:[\'"\(\[])?([a-z]:[\\/][^\s]*)'
)

# Match relative paths commonly used in the project (e.g. tmp/file.txt, ./file.txt, ../file.txt).
# Conservative: requires a slash and a filename-like extension, or starts with tmp/ or ./ or ../.
_RELATIVE_PATH_RE = re.compile(
    r'(?i)(?<![\w/])(?:[\'"\(\[])?((?:tmp|\.\.?|src|tests|docs|data|config|system|memory|scripts|tools)(?:/[a-zA-Z0-9_.-]+)+\.[a-zA-Z0-9]+|[a-zA-Z0-9_.-]+\.[a-zA-Z0-9]+)'
)

# Match URLs (http/https only). Captures broad URL string; trailing punctuation stripped during normalization.
_URL_RE = re.compile(
    r'(?i)(https?://[^\s"\'\)]+)'
)

# Match bare filenames (no directory prefix) that appear in a clear file-operation context.
# Requires:
#   - a contextual anchor keyword (named, called, file, from, read, write, create, edit, append)
#     immediately before the filename (with optional whitespace and optional quote)
#   - a filename with a dot-separated extension (1-10 chars)
#   - no slash or backslash in the captured name (those are handled by _PATH_RE/_RELATIVE_PATH_RE)
#   - not URL-like (no http/https prefix)
# Conservative: keyword must appear directly before the filename in the same clause.
_BARE_FILENAME_RE = re.compile(
    r'(?i)(?:named?|called|file|from|read|write|create|edit|append|to|into)\s+[\'"]?([a-zA-Z0-9_.-]+\.[a-zA-Z0-9]{1,10})[\'"]?(?=\s|$|[,;.!?\)])'
)

# Internet TLDs that must NOT be treated as file extensions in bare-filename extraction.
# Prevents "Read example.com" or "Write to api.io" from creating false local file paths.
_INTERNET_TLDS = frozenset([
    "com", "org", "net", "io", "edu", "gov", "co", "uk", "de", "fr", "au",
    "ca", "ru", "jp", "cn", "br", "in", "mx", "nl", "se", "no", "fi",
    "html", "htm",  # web page extensions — not local file artifacts
])

# Match same-file reference phrases: used in B3 create->write cross-path binding.
# These phrases signal that the current step refers to the same file as a prior step
# without repeating the filename.
_SAME_FILE_REF_RE = re.compile(
    r'(?i)\b(?:newly[ -]created file|the new(?:ly)?(?:\s+created)?\s+file|the same file|'
    r'the file|that file|same file|this file)\b'
)


def _extract_local_file_paths(text: str) -> list[str]:
    """Extract concrete local file paths (absolute and relative) from step text."""
    if not text:
        return []
    paths = []
    seen: set[str] = set()

    def _add(p: str) -> None:
        if p not in seen:
            seen.add(p)
            paths.append(p)

    for match in _PATH_RE.finditer(text):
        path = match.group(1)
        # Basic structural guard: must be drive-letter absolute
        if len(path) >= 3 and path[1] == ":" and path[2] in "\\/":
            _add(path)
    for match in _RELATIVE_PATH_RE.finditer(text):
        path = match.group(1)
        # Must contain a slash to be a relative path; single filenames are too ambiguous
        if "/" in path or "\\" in path:
            _add(path)
    # Bare filenames: only when a file-operation keyword anchors the filename in context.
    # Skip if the text already contains a URL (reduces false positives on URL-heavy purposes).
    if not _URL_RE.search(text):
        for match in _BARE_FILENAME_RE.finditer(text):
            path = match.group(1)
            # Must not be URL-like and must have no directory separator
            if "/" not in path and "\\" not in path and not re.match(r'(?i)^https?', path):
                # Reject internet TLDs masquerading as file extensions
                ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
                base = path.rsplit(".", 1)[0] if "." in path else path
                if ext in _INTERNET_TLDS:
                    continue
                # Require base name of at least 2 characters
                if len(base) < 2:
                    continue
                _add(path)
    return paths


def _normalize_local_file_path(path: str) -> str | None:
    """
    Normalize an extracted local file path string.

    Returns None if:
      - path is a URL
      - path is empty after stripping
    """
    if not path:
        return None
    # Reject URLs
    if re.match(r'(?i)^https?://', path):
        return None
    # Strip surrounding quotes/brackets
    path = path.strip('"\'()[]')
    # Lowercase and slash-normalize for cross-platform comparison
    path = path.lower().replace('\\', '/')
    # Strip trailing punctuation that may have been captured
    path = path.rstrip('.,;:!?\'"')
    # Reject if stripped to drive letter only or empty
    if len(path) <= 3:
        return None
    return path


def _extract_urls(text: str) -> list[str]:
    """Extract concrete http/https URLs from step text."""
    if not text:
        return []
    return [match.group(1) for match in _URL_RE.finditer(text)]


def _normalize_url(url: str) -> str | None:
    """Normalize an extracted URL for comparison."""
    if not url:
        return None
    url = url.strip('"\'()[]')
    url = url.rstrip('.,;:!?')
    if not re.match(r'(?i)^https?://', url):
        return None
    return url.lower()
def _classify_file_operation(step: dict) -> str:
    """
    Conservative keyword-based classification of local file operation type.

    Returns one of: "write", "read", "edit", "file_consumer", "unknown".
    """
    text = (step.get("purpose", "") + " " + step.get("expected_outcome", "")).lower()

    for marker in _WRITE_MARKERS:
        if marker in text:
            return "write"
    for marker in _EDIT_MARKERS:
        if marker in text:
            return "edit"
    for marker in _READ_MARKERS:
        if marker in text:
            return "read"

    # If the step references a file path but does not perform an explicit file operation,
    # classify it as a consumer (e.g., summarize, report, analyze) so it can depend
    # on the prior file step.
    # Synthesis-only steps are NOT consumers; they should consume prior outputs via
    # explicit dependency references, not inherit the same resource.
    if _extract_local_file_paths(text):
        if _is_synthesis_only_step(step):
            return "unknown"
        consumer_markers = [
            "summarize", "summary", "report", "analyze", "analyse", "describe",
            "explain", "discuss", "present", "outline", "overview", "interpret",
        ]
        if any(marker in text for marker in consumer_markers):
            return "file_consumer"

    return "unknown"


def _classify_web_operation(step: dict) -> str:
    """
    Conservative keyword-based classification of web operation type.

    Returns one of: "web_read", "web_write", "web_edit", "web_consumer", "unknown".
    """
    text = (step.get("purpose", "") + " " + step.get("expected_outcome", "")).lower()

    for marker in _WEB_WRITE_MARKERS:
        if marker in text:
            return "web_write"
    for marker in _WEB_EDIT_MARKERS:
        if marker in text:
            return "web_edit"
    for marker in _WEB_READ_MARKERS:
        if marker in text:
            return "web_read"

    # If the step references a URL but does not perform an explicit web operation,
    # classify it as a consumer (e.g., summarize, report, analyze) so it can depend
    # on the prior web_read step.
    # Synthesis-only steps are NOT consumers; they should consume prior outputs via
    # explicit dependency references, not inherit the same resource.
    if _extract_urls(text):
        if _is_synthesis_only_step(step):
            return "unknown"
        consumer_markers = [
            "summarize", "summary", "report", "analyze", "analyse", "describe",
            "explain", "discuss", "present", "outline", "overview", "interpret",
        ]
        if any(marker in text for marker in consumer_markers):
            return "web_consumer"

    return "unknown"


def _requires_same_resource_sequence(prev_op: str, curr_op: str, user_input: str | None = None) -> bool:
    """
    Determine whether a prior operation on the same resource requires the
    current step to depend on it.

    Approved deterministic patterns for local files:
      write -> read | edit | write
      edit  -> read | edit

    Conditional pattern for local files (requires user_input sequence markers):
      read -> edit

    Web patterns (URLs):
      web_read -> web_read | web_edit | web_write
    """
    # Local file patterns
    if prev_op == "write" and curr_op in ("read", "edit", "write", "file_consumer"):
        return True
    if prev_op == "edit" and curr_op in ("read", "edit", "file_consumer"):
        return True
    if prev_op == "read" and curr_op == "file_consumer":
        return True

    if prev_op == "read" and curr_op == "edit":
        if not user_input:
            return False
        ui = user_input.lower()
        return any(marker in ui for marker in _SEQUENCE_MARKERS)

    # Web URL patterns
    if prev_op == "web_read" and curr_op in ("web_read", "web_edit", "web_write", "web_consumer"):
        return True

    return False


def _add_dependency_if_missing(step: dict, dep_id: str) -> bool:
    """Append dep_id to step depends_on if absent. Preserves order."""
    deps = step.get("depends_on", []) or []
    if not isinstance(deps, list):
        deps = []
    if dep_id in deps:
        return False
    step["depends_on"] = deps + [dep_id]
    return True


def apply_resource_sequencing_binding(workflow: dict, user_input: str | None = None) -> dict:
    """
    Deterministically repair missing same-resource sequencing dependencies.

    Covers both local file paths (absolute and relative) and URLs.

    Rules (per PLANNING_COMPILER_CONTRACT_V1 §11):
      1. Only operates on steps already in the plan.
      2. Only repairs when both steps reference the same concrete normalized resource:
         a local file path (absolute or relative) or a URL.
         A step also inherits resources from explicitly-declared prior step dependencies,
         enabling transitive same-resource sequencing when a step references a prior
         step's output without repeating the resource identifier.
      3. Only adds dependency from later step -> most recent prior step on same resource.
      4. Only repairs when operation pairing requires ordering.
      5. Existing dependencies are preserved and deduped.
      6. Does NOT create new steps, delete steps, modify purpose, or modify agent selection.
      7. Idempotent: running twice produces the same result.

    Args:
        workflow: workflow dict with "steps" list
        user_input: optional original user input for conditional read->edit detection

    Returns:
        Repaired workflow dict (mutates in place for efficiency, but conceptually pure).
    """
    steps = workflow.get("steps", [])
    if not isinstance(steps, list) or len(steps) <= 1:
        return workflow

    # Pre-compute metadata for every step to support transitive resource inheritance
    step_meta: dict[str, dict] = {}
    for step in steps:
        step_id = step.get("id")
        if not step_id:
            continue
        text = (step.get("purpose", "") + " " + step.get("expected_outcome", "")).strip()
        own_paths = set()
        for path in _extract_local_file_paths(text):
            norm = _normalize_local_file_path(path)
            if norm:
                own_paths.add(norm)
        own_urls = set()
        for url in _extract_urls(text):
            norm = _normalize_url(url)
            if norm:
                own_urls.add(norm)
        file_op = _classify_file_operation(step)
        web_op = _classify_web_operation(step)
        op = web_op if web_op != "unknown" else file_op
        step_meta[step_id] = {
            "paths": own_paths,
            "urls": own_urls,
            "op": op,
        }

    # === B3 pass: create->write cross-path binding ===
    # When a prior step creates/writes exactly one file and a later step:
    #   (a) has no own file paths in its purpose, OR
    #   (b) its purpose contains a same-file reference phrase
    # bind the later step to the prior step and let apply_resource_reference_restoration
    # rewrite the purpose with the correct path.
    # Only activates when the current step is a write/edit operation (not read — Patch B covers that).
    for i, step in enumerate(steps):
        step_id = step.get("id")
        if not step_id:
            continue
        meta = step_meta[step_id]
        # Only repair write/edit steps that lack their own file path
        if meta["op"] not in ("write", "edit"):
            continue
        purpose = step.get("purpose", "")
        has_same_file_ref = bool(_SAME_FILE_REF_RE.search(purpose))
        has_own_path = bool(meta["paths"])
        if not has_same_file_ref and has_own_path:
            # Step has its own explicit path and no same-file reference: don't interfere
            continue
        # Find the nearest prior write/edit step with exactly one path
        for j in range(i - 1, -1, -1):
            prior = steps[j]
            prior_id = prior.get("id")
            if not prior_id:
                continue
            prior_meta = step_meta.get(prior_id)
            if not prior_meta:
                continue
            if prior_meta["op"] not in ("write", "edit"):
                continue
            if len(prior_meta["paths"]) != 1:
                continue
            prior_path = next(iter(prior_meta["paths"]))
            # Guard: if current step has an explicit path that differs from prior's,
            # only skip when there is no same-file reference phrase.
            # When a same-file phrase is present ("newly created file", "the file", etc.)
            # it signals intent to use the prior file, so bind regardless of path mismatch.
            if has_own_path and prior_path not in meta["paths"] and not has_same_file_ref:
                continue
            _add_dependency_if_missing(step, prior_id)
            break

    # resource -> (last_step_index, last_step_id, last_op)
    last_op_by_resource: dict[str, tuple[int, str, str]] = {}

    for i, step in enumerate(steps):
        step_id = step.get("id")
        if not step_id:
            continue

        meta = step_meta[step_id]
        op = meta["op"]
        if op == "unknown":
            continue

        # Collect resources from step text + from explicitly-declared prior dependencies
        resources = set(meta["paths"])
        resources.update(meta["urls"])
        for dep_id in step.get("depends_on", []) or []:
            dep_meta = step_meta.get(dep_id)
            if dep_meta:
                resources.update(dep_meta["paths"])
                resources.update(dep_meta["urls"])

        for resource in resources:
            if resource in last_op_by_resource:
                _prior_idx, prior_id, prior_op = last_op_by_resource[resource]
                if _requires_same_resource_sequence(prior_op, op, user_input):
                    _add_dependency_if_missing(step, prior_id)

            last_op_by_resource[resource] = (i, step_id, op)

    return workflow


def apply_vague_sequential_dependency_repair(workflow: dict) -> dict:
    """
    Deterministically repair missing dependencies for singular sequential vague references.
    
    Sprint 9D-3B Phase 1: Repair obvious singular sequential chain dependencies 
    before validation, so natural chained prompts can execute correctly.
    
    Rules:
      1. Only operates on steps with singular vague references (the result, that result, previous result, prior result)
      2. Only repairs when step is not first step and has no existing depends_on
      3. Only repairs when step does not contain explicit step_X references
      4. Only repairs sequential arithmetic/action continuation patterns
      5. Only repairs when immediately previous step is a safe chain source
      6. Does not repair steps marked "separately"
      7. Does not repair final synthesis/list/report wording
      8. Does not repair plural references (the results, those results, etc.)
      9. Idempotent: running twice produces the same result
      10. Preserves existing valid dependencies
    
    Args:
        workflow: workflow dict with "steps" list
        
    Returns:
        Repaired workflow dict (mutates in place for efficiency, but conceptually pure)
    """
    steps = workflow.get("steps", [])
    if not isinstance(steps, list) or len(steps) <= 1:
        return workflow
    
    # Keywords that indicate singular vague references
    singular_vague_keywords = ["the result", "that result", "previous result", "prior result"]
    
    # Keywords that indicate plural references (explicitly rejected)
    plural_keywords = ["the results", "those results", "these results", "all results", "both results"]
    
    # Keywords that indicate final synthesis/reporting (explicitly rejected)
    synthesis_keywords = ["list", "report", "show", "give", "final", "answer", "summarize", "combine"]
    
    # Sequential action verbs that indicate chain continuation
    sequential_verbs = ["multiply", "divide", "add", "subtract", "square", "cube", "power", "mod", "calculate"]
    
    for i, step in enumerate(steps):
        step_id = step.get("id", f"step_{i+1}")
        purpose = step.get("purpose", "").lower()
        expected_outcome = step.get("expected_outcome", "").lower()
        combined_text = purpose + " " + expected_outcome
        
        # Rule 1: Skip if already has dependencies
        if step.get("depends_on") and len(step.get("depends_on", [])) > 0:
            continue
            
        # Rule 2: Skip first step
        if i == 0:
            continue
            
        # Rule 3: Skip if contains explicit step_X references
        if "step_" in combined_text:
            continue
            
        # Rule 4: Skip if contains plural references
        if any(plural in combined_text for plural in plural_keywords):
            continue
            
        # Rule 5: Skip if marked "separately"
        if "separately" in combined_text:
            continue
            
        # Rule 6: Skip if final synthesis/reporting wording
        if any(synthesis in combined_text for synthesis in synthesis_keywords):
            continue
            
        # Rule 7: Must contain singular vague reference
        if not any(vague in combined_text for vague in singular_vague_keywords):
            continue
            
        # Rule 8: Must indicate sequential action continuation
        if not any(verb in purpose for verb in sequential_verbs):
            continue
            
        # Rule 9: Previous step must be a safe chain source
        prev_step = steps[i-1]
        prev_step_id = prev_step.get("id", f"step_{i}")
        prev_purpose = prev_step.get("purpose", "").lower()
        
        # Don't chain from synthesis steps or steps marked "separately"
        if any(synthesis in prev_purpose for synthesis in synthesis_keywords):
            continue
        if "separately" in prev_purpose:
            continue
            
        # All conditions met - apply repair
        if "depends_on" not in step:
            step["depends_on"] = []
        step["depends_on"] = [prev_step_id]
    
    return workflow


def apply_branch_terminal_synthesis_binding(workflow: dict) -> dict:
    """
    Sprint 9D-3G: Bind final synthesis steps to branch terminal outputs only.
    
    For eligible final synthesis steps, bind them to prior branch terminal outputs
    so they receive the actual source outputs instead of running independently.
    
    Eligibility rules (all must be true):
    1. Final step in workflow
    2. No existing depends_on
    3. Clear final/listing/answer/result-output intent
    4. References multiple outputs conceptually
    5. At least two prior branch-terminal source steps
    6. Not concrete arithmetic/action/file/web/read step
    7. No explicit step_X references
    
    Args:
        workflow: workflow dict with "steps" list
        
    Returns:
        workflow dict with branch-terminal synthesis binding applied
    """
    from system.orchestrator.synthesis_dependency_utils import (
        _is_branch_terminal_synthesis_step,
        _identify_branch_terminals
    )
    
    steps = workflow.get("steps", [])
    if not isinstance(steps, list) or len(steps) < 2:
        return workflow
    
    total_steps = len(steps)
    
    # Check each step for branch-terminal synthesis eligibility
    for i, step in enumerate(steps):
        if _is_branch_terminal_synthesis_step(step, i, total_steps, steps):
            # Identify branch terminals from prior steps (exclude final step)
            prior_steps = steps[:i]
            terminal_steps = _identify_branch_terminals(prior_steps)
            
            # Apply binding to branch terminals
            if terminal_steps and len(terminal_steps) >= 2:
                if "depends_on" not in step:
                    step["depends_on"] = []
                step["depends_on"] = terminal_steps
                break  # Only apply to final step
    
    return workflow