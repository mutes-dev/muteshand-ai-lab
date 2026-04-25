INPUT_SPEC = {
    "section": "string"
}

def run(section):
    """
    Smarter inspector: finds any section in manager.py by keyword match.
    Returns up to 60 lines of context around the first strong match.
    Pure string search – no LLM.
    """
    import os
    import re
    from core.config import BASE_PATH

    path = BASE_PATH / "projects" / "manager" / "manager.py"
    if not path.exists():
        return f"ERROR: manager.py not found at {path}"

    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    section = section.lower().strip()

    # Keyword patterns – add more as we discover needed blocks
    patterns = {
        "main_loop":        r"(?i)manager\s*loop|while\s*true",
        "step_progression": r"(?i)current_step|step\s*advance|completed_steps|next_step",
        "repair_mode":      r"(?i)repair_mode|repair\s*attempts|repair_limit",
        "failed_tool":      r"(?i)failed_tool|tester\s*failure",
        "final_answer":     r"(?i)final\s*answer|fabricated|override",
        "task_state":       r"(?i)task_state|current_step\s*=\s*0",
        "agent_result":     r"(?i)agent\s*result|agent\s*action|handle_agent",
        "tester_failure":   r"(?i)tester\s*failure|test\s*failed",
        "enforce_limit":    r"(?i)enforce\s*repair\s*limit|max_repair"
    }

    # Find best matching pattern
    best_pattern = None
    best_key = None
    for key, pat in patterns.items():
        if re.search(pat, section) or key in section:
            best_pattern = pat
            best_key = key
            break

    if not best_pattern:
        # Fallback: treat input as raw keyword
        best_pattern = re.escape(section)
        best_key = section

    # Search for first line that matches
    match_line_idx = -1
    for i, line in enumerate(lines):
        if re.search(best_pattern, line, re.IGNORECASE):
            match_line_idx = i
            break

    if match_line_idx == -1:
        # No exact match → suggest similar lines
        suggestions = []
        for i, line in enumerate(lines):
            if section in line.lower() or any(w in line.lower() for w in section.split()):
                suggestions.append(f"Line {i+1}: {line.strip()}")
        if suggestions:
            return f"No strong match for '{section}'.\nPossible related lines:\n" + "\n".join(suggestions[:5])
        return f"No match found for '{section}' in manager.py"

    # Capture context: 20 lines before + 40 after (or file bounds)
    start = max(0, match_line_idx - 20)
    end = min(len(lines), match_line_idx + 41)
    excerpt = lines[start:end]

    # Add header with match info
    header = [
        f"# MATCH: '{best_key}' (pattern: {best_pattern}) at line {match_line_idx+1}",
        f"# CONTEXT LINES {start+1}–{end}",
        "-" * 60
    ]

    return "\n".join(header + [line.rstrip() for line in excerpt])