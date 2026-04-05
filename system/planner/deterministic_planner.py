def plan(user_input: str) -> list | dict:
    """
    Deterministic Planner - STRICT TOOL IDENTITY ENFORCEMENT
    
    Rules:
    - NO substring matching
    - NO partial matches
    - ONLY exact tool names or explicitly defined phrases
    - Word boundary enforcement for all matches
    """
    import json
    import os
    import re

    tools_path = os.path.join("memory", "tool_index", "tools.json")

    with open(tools_path, "r") as f:
        tool_index = json.load(f)

    if isinstance(tool_index, dict):
        VALID_TOOL_IDS = set(tool_index.keys())
    elif isinstance(tool_index, list):
        VALID_TOOL_IDS = set(tool["name"] for tool in tool_index)
    else:
        raise ValueError("Invalid tool_index structure")

    # EXPLICIT PHRASE MAPPING - CONTROLLED ONLY
    TOOL_PHRASES = {
        "add_numbers": ["add", "sum", "addition"],
        "subtract_numbers": ["subtract", "difference", "minus"],
        "multiply_numbers": ["multiply", "product", "times"],
        # NEW (BATCH 1)
        "divide_numbers": ["divide"],
        "square_number": ["square"],
        "cube_number": ["cube"],
        "factorial": ["factorial"],
        "fibonacci": ["fibonacci"],
        # NEW (BATCH 2)
        "square_root": ["root"],
        "multiply_square_root": ["multisqrt"],
        "test_valid_add": ["validadd"],
        "bad_add": ["badadd"],
        "broken_add": ["brokenadd"]
    }

    # OBSERVABILITY: Debug mode flag (disabled by default)
    #DEBUG_MODE = False
    DEBUG_MODE = True

    def normalize(text: str) -> str:
        """Normalize input: lowercase and strip whitespace."""
        return text.lower().strip()

    def normalize_input(text: str) -> str:
        """
        Deterministic normalization for known simple patterns.
        DOES NOT modify original input_text (used only internally).
        """
        tokens = text.strip().split()

        # Ensure minimal structure: keyword + number
        if len(tokens) == 2:
            keyword, value = tokens

            # STRICT keyword mapping ONLY
            if keyword == "square":
                return f"square_number {value}"

            if keyword == "cube":
                return f"cube_number {value}"

            if keyword == "factorial":
                return f"factorial {value}"

            if keyword == "fibonacci":
                return f"fibonacci {value}"

        return text

    def matches_exact_tool_name(normalized: str, tool_name: str) -> bool:
        """
        Check if normalized input starts with EXACT tool name at word boundary.
        Example: 'add_numbers 2 and 3' matches 'add_numbers'
        Example: 'bad_add 2 and 3' does NOT match 'add_numbers'
        """
        # Match tool name at start, followed by word boundary (space, end, or non-word)
        pattern = r'^' + re.escape(tool_name) + r'\b'
        return bool(re.match(pattern, normalized))

    def matches_tool_phrase(normalized: str, tool_name: str, phrases: list) -> bool:
        """
        Check if normalized input starts with ANY of the explicit phrases for this tool.
        Phrase must match as FULL WORD (word boundary).
        Example: 'add 2 and 3' matches phrase 'add'
        Example: 'bad_add 2 and 3' does NOT match phrase 'add'
        """
        for phrase in phrases:
            # Match phrase at start, followed by word boundary
            pattern = r'^' + re.escape(phrase) + r'\b'
            if re.match(pattern, normalized):
                return True
        return False

    def identify_tool(segment: str) -> str | None:
        """
        Identify tool from segment using STRICT matching.
        
        Order of matching:
        1. NORMALIZE simple patterns (keyword + value -> full tool name)
        2. EXACT tool name match (word boundary enforced)
        3. EXPLICIT PHRASE mapping (word boundary enforced)
        
        Returns tool name or None if no match.
        """
        # STEP 0: Normalize simple patterns BEFORE matching
        normalized_segment = normalize_input(segment)
        normalized = normalize(normalized_segment)

        # STEP 1: Check EXACT tool name match
        for tool_name in VALID_TOOL_IDS:
            if matches_exact_tool_name(normalized, tool_name):
                return tool_name

        # STEP 2: Check EXPLICIT PHRASE mapping
        for tool_name, phrases in TOOL_PHRASES.items():
            if matches_tool_phrase(normalized, tool_name, phrases):
                return tool_name

        # No match found
        return None

    def validate_step(step: dict):
        """
        Enforce strict planner step structure invariant.
        FAIL-FAST if invalid.
        """
        if not isinstance(step, dict):
            raise RuntimeError("planner_invariant_violation")

        required_keys = {"type", "name", "input_text"}

        if not required_keys.issubset(step.keys()):
            raise RuntimeError("planner_invariant_violation")

        # Validate values
        if step.get("type") != "tool":
            raise RuntimeError("planner_invariant_violation")

        if not isinstance(step.get("name"), str) or not step["name"]:
            raise RuntimeError("planner_invariant_violation")

        if not isinstance(step.get("input_text"), str) or not step["input_text"]:
            raise RuntimeError("planner_invariant_violation")

    segments = user_input.split(" then ")
    steps = []
    # OBSERVABILITY: Collect traces for all segments
    traces = []

    for segment in segments:
        # OBSERVABILITY: Initialize trace for this segment
        trace = {
            "original_input": None,
            "normalized_input": None,
            "matched_tool": None,
            "exposure_allowed": None
        }
        traces.append(trace)

        # Preserve original input_text for output
        original_segment = segment.strip()
        trace["original_input"] = original_segment

        # Identify tool with STRICT matching
        tool_name = identify_tool(segment)
        trace["matched_tool"] = tool_name

        # Capture normalized input for observability
        normalized_segment = normalize_input(segment)
        trace["normalized_input"] = normalized_segment if normalized_segment != original_segment else original_segment

        # FAIL-FAST: Return immediately if tool not found
        if tool_name is None or tool_name not in VALID_TOOL_IDS:
            trace["exposure_allowed"] = False
            result = {
                "status": "failure",
                "reason": "unknown_tool"
            }
            if DEBUG_MODE:
                result["trace"] = traces
            return result

        # PRODUCTION ENFORCEMENT: Only route to production-safe tools (via tool_index)
        tool_meta = tool_index.get(tool_name)
        if not tool_meta or tool_meta.get("production") is not True:
            trace["exposure_allowed"] = False
            result = {
                "status": "failure",
                "reason": "unknown_tool"
            }
            if DEBUG_MODE:
                result["trace"] = traces
            return result

        trace["exposure_allowed"] = True

        steps.append({
            "type": "tool",
            "name": tool_name,
            "input_text": original_segment
        })

    # INVARIANT: Validate all steps before return
    for step in steps:
        validate_step(step)

    # OBSERVABILITY: Include trace in debug mode (additive only)
    result = {
        "status": "success",
        "steps": steps
    }
    if DEBUG_MODE:
        result["trace"] = traces

    return result
