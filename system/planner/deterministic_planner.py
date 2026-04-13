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

    tools_path = os.path.join("system", "tool_index", "tools.json")

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
        "multiply_numbers": ["multiply", "product"],
        # NEW (BATCH 1)
        "divide_numbers": ["divide"],
        "square_number": ["square"],
        "cube_number": ["cube"],
        "factorial": ["factorial"],
        "fibonacci": ["fibonacci"],
        # NEW (BATCH 2)
        "square_root": ["square root", "root"],
        "multiply_string": ["multiply string", "repeat"],
        "test_valid_add": ["validadd"],
        "bad_add": ["badadd"],
        "broken_add": ["brokenadd"],
        # PHASE 1: FILE/WEB TOOLS
        "list_files": ["list files"],
        "read_file": ["read file"],
        "read_webpage": ["read webpage"],
        "web_search": ["web search", "search"],
        "write_file": ["write file", "write"]
    }

    # OBSERVABILITY: Debug mode flag (disabled by default)
    #DEBUG_MODE = False
    DEBUG_MODE = True

    def matches_exact_tool_name(text: str, tool_name: str) -> bool:
        """
        Check if input starts with EXACT tool name at word boundary.
        Example: 'add_numbers 2 and 3' matches 'add_numbers'
        Example: 'bad_add 2 and 3' does NOT match 'add_numbers'
        Input is already normalized by pre-planner layer.
        """
        # Match tool name at start, followed by word boundary (space, end, or non-word)
        pattern = r'^' + re.escape(tool_name) + r'\b'
        return bool(re.match(pattern, text))

    def matches_tool_phrase(text: str, tool_name: str, phrases: list) -> bool:
        """
        Check if input starts with ANY of the explicit phrases for this tool.
        Phrase must match as FULL WORD (word boundary).
        Example: 'add 2 and 3' matches phrase 'add'
        Example: 'bad_add 2 and 3' does NOT match phrase 'add'
        Input is already normalized by pre-planner layer.
        """
        for phrase in phrases:
            # Match phrase at start, followed by word boundary
            pattern = r'^' + re.escape(phrase) + r'\b'
            if re.match(pattern, text):
                return True
        return False

    def priority_score(tool_name):
        """Calculate priority score - longer names = more specific = higher priority."""
        return len(tool_name)

    def identify_tool(segment: str) -> str | None | dict:
        """
        Identify tool from segment using STRICT matching with AMBIGUITY DETECTION.
        Input is already normalized by pre-planner layer.
        
        Order of matching:
        1. EXACT tool name match (word boundary enforced)
        2. EXPLICIT PHRASE mapping (all phrases evaluated, ambiguity detected)
        3. MULTI-PHRASE AMBIGUITY: Detect if multiple different tool phrases appear in input
        
        Returns:
            - str (tool name) if single match found
            - None if no match found
            - dict {"status": "failure", "reason": "ambiguous_instruction"} if multiple matches
        """
        # Input is already normalized upstream
        text = segment.strip()
        
        # COLLECT ALL MATCHES with phrase length info for overlap resolution
        # Format: (tool_name, phrase_length)
        all_matches = {}

        # STEP 1: Check EXACT tool name match
        tools_sorted = sorted(VALID_TOOL_IDS, key=lambda t: priority_score(t), reverse=True)
        for tool_name in tools_sorted:
            if matches_exact_tool_name(text, tool_name):
                # Tool names match at position 0 with length = len(tool_name)
                all_matches[tool_name] = len(tool_name)

        # STEP 2: Check ALL EXPLICIT PHRASE mappings at start (prefix matching)
        # Build flattened phrase map: (tool_name, phrase) tuples
        phrase_map = []
        for tool_name, phrases in TOOL_PHRASES.items():
            for phrase in phrases:
                phrase_map.append((tool_name, phrase))
        
        # Evaluate ALL phrases at start (no early return - collect all matches)
        for tool_name, phrase in phrase_map:
            pattern = r'^' + re.escape(phrase) + r'\b'
            if re.match(pattern, text):
                # Store the longest matching phrase for each tool
                if tool_name not in all_matches or len(phrase) > all_matches[tool_name]:
                    all_matches[tool_name] = len(phrase)

        # STEP 3: MULTI-PHRASE AMBIGUITY DETECTION
        # Check if multiple DIFFERENT tool phrases appear anywhere in the input
        # This detects cases like "add and multiply 2 and 3" where both "add" and "multiply" appear
        tools_at_positions = {}  # tool_name -> list of match positions
        for tool_name, phrase in phrase_map:
            # Check if phrase appears anywhere in input (with word boundary)
            search_pattern = r'\b' + re.escape(phrase) + r'\b'
            for match in re.finditer(search_pattern, text):
                if tool_name not in tools_at_positions:
                    tools_at_positions[tool_name] = []
                tools_at_positions[tool_name].append((match.start(), len(phrase)))
        
        # If multiple different tools detected in input
        if len(tools_at_positions) > 1:
            # Check if all tools match at the same position (position 0 - overlapping)
            all_at_position_zero = all(
                any(pos == 0 for pos, length in positions)
                for positions in tools_at_positions.values()
            )
            
            if all_at_position_zero:
                # All tools match at position 0 - use longest match wins (overlap resolution)
                # Find the longest match among position 0 matches
                longest_at_zero = {}
                for tool_name, positions in tools_at_positions.items():
                    for pos, length in positions:
                        if pos == 0:
                            longest_at_zero[tool_name] = max(longest_at_zero.get(tool_name, 0), length)
                
                max_length = max(longest_at_zero.values())
                longest_tools = [t for t, l in longest_at_zero.items() if l == max_length]
                
                if len(longest_tools) == 1:
                    # Longest phrase wins - return dict with matched phrase
                    tool_name = longest_tools[0]
                    return {"tool_name": tool_name, "matched_phrase": segment[:max_length]}
                else:
                    # Multiple tools with same max length at position 0
                    return {"status": "failure", "reason": "ambiguous_instruction"}
            else:
                # Tools appear at different positions → AMBIGUOUS
                return {"status": "failure", "reason": "ambiguous_instruction"}

        # AMBIGUITY DETECTION with OVERLAP RESOLUTION (for prefix matches only)
        if len(all_matches) == 0:
            # No match found
            return None
        elif len(all_matches) == 1:
            # Single match - proceed normally
            tool_name = list(all_matches.keys())[0]
            matched_len = all_matches[tool_name]
            return {"tool_name": tool_name, "matched_phrase": segment[:matched_len]}
        else:
            # Multiple matches at start - check if they overlap at same position
            # Find the longest match length
            max_length = max(all_matches.values())
            # Find tools that match with the maximum length (overlapping at position 0)
            longest_matches = {tool for tool, length in all_matches.items() if length == max_length}
            
            if len(longest_matches) == 1:
                # Longest phrase wins (overlapping phrases resolved by length)
                tool_name = longest_matches.pop()
                # Return both tool_name and the matched phrase for clean_input extraction
                return {"tool_name": tool_name, "matched_phrase": segment[:max_length]}
            else:
                # Multiple different tools with same max length - AMBIGUOUS
                return {"status": "failure", "reason": "ambiguous_instruction"}

    def validate_step(step: dict):
        """
        Enforce strict planner step structure invariant.
        FAIL-FAST if invalid.
        """
        if not isinstance(step, dict):
            raise RuntimeError("planner_invariant_violation")

        # PHASE 1-2: clean_input is now optional (added non-breaking)
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

        # Identify tool with STRICT matching (includes ambiguity detection)
        tool_result = identify_tool(segment)
        
        # Handle AMBIGUITY DETECTION result
        if isinstance(tool_result, dict) and tool_result.get("reason") == "ambiguous_instruction":
            trace["matched_tool"] = None
            trace["exposure_allowed"] = False
            result = {
                "status": "failure",
                "reason": "ambiguous_instruction"
            }
            if DEBUG_MODE:
                result["trace"] = traces
            return result
        
        # Extract tool_name and matched_phrase from result
        tool_name = tool_result["tool_name"]
        matched_phrase = tool_result["matched_phrase"]
        
        # PHASE 1-2: Strip matched phrase to create clean_input
        clean_input = segment[len(matched_phrase):].strip()
        trace["matched_tool"] = tool_name

        # Input is already normalized upstream - use original for trace
        trace["normalized_input"] = original_segment

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

        # TRACE LOGGING for debugging tool selection
        print(f"[PLANNER_TRACE] input={original_segment}")
        print(f"[PLANNER_TRACE] clean_input={clean_input}")
        print(f"[PLANNER_TRACE] selected_tool={tool_name}")

        steps.append({
            "type": "tool",
            "name": tool_name,
            "input_text": original_segment,
            "clean_input": clean_input
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
