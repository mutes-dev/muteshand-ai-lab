def normalize_input(text: str) -> str:
    """
    Pre-planner normalization.

    Allowed:
    - lowercase
    - strip whitespace
    - remove fixed noise tokens

    Forbidden:
    - semantic mapping
    - argument modification
    - token reordering
    """

    # STEP 0: Extract quoted segments to preserve them exactly
    # Quoted content must not be modified (including newlines)
    quoted_segments = []
    placeholder_prefix = "\x00quoted"

    def extract_quotes(s):
        """Extract quoted segments and replace with placeholders."""
        result = []
        i = 0
        quote_count = 0
        while i < len(s):
            if s[i] == '"':
                # Find closing quote
                j = i + 1
                while j < len(s) and s[j] != '"':
                    j += 1
                if j < len(s):
                    # Found closing quote
                    quoted_content = s[i:j+1]  # Include quotes
                    placeholder = f"{placeholder_prefix}{quote_count}\x00"
                    quoted_segments.append(quoted_content)
                    result.append(placeholder)
                    quote_count += 1
                    i = j + 1
                else:
                    # No closing quote - treat as regular character
                    result.append(s[i])
                    i += 1
            else:
                result.append(s[i])
                i += 1
        return ''.join(result)

    def restore_quotes(s):
        """Restore quoted segments from placeholders."""
        for i, content in enumerate(quoted_segments):
            placeholder = f"{placeholder_prefix}{i}\x00"
            s = s.replace(placeholder, content, 1)
        return s

    text = extract_quotes(text)

    # STEP 1: Normalize non-quoted text
    text = text.lower().strip()

    NOISE_WORDS = ["please", "hey", "can you", "what is"]

    # STEP 2: Iterative prefix removal (handles multiple noise words)
    changed = True
    while changed:
        changed = False
        for word in NOISE_WORDS:
            if text.startswith(word + " "):
                text = text[len(word) + 1:]
                changed = True

    # STEP 3: Trailing noise removal (single pass only)
    TRAILING_NOISE = ["please", "thanks"]

    for word in TRAILING_NOISE:
        if text.endswith(" " + word):
            text = text[:-(len(word) + 1)]

    # STEP 4: Whitespace normalization (ONLY on non-quoted portions)
    # Ensure spaces around placeholders for proper tokenization
    import re
    # Add spaces around placeholders if missing
    text = re.sub(rf'({placeholder_prefix}\d+\x00)', r' \1 ', text)
    text = re.sub(r'\s+', ' ', text).strip()  # Collapse multiple spaces

    # Now process: split by placeholders, normalize non-quoted, restore
    # Find all placeholder positions
    pattern = rf'{placeholder_prefix}(\d+)\x00'
    matches = list(re.finditer(pattern, text))

    if not matches:
        # No quoted segments - normalize entire text
        text = " ".join(text.split())
    else:
        # Build normalized string with proper spacing
        result_parts = []
        last_end = 0

        for match in matches:
            # Get text before this placeholder
            before = text[last_end:match.start()]
            # Normalize the before portion
            normalized_before = " ".join(before.split())
            if normalized_before:
                result_parts.append(normalized_before)

            # Add placeholder (will be restored later)
            result_parts.append(match.group(0))
            last_end = match.end()

        # Get remaining text after last placeholder
        after = text[last_end:]
        normalized_after = " ".join(after.split())
        if normalized_after:
            result_parts.append(normalized_after)

        text = ' '.join(result_parts)

    # STEP 5: Restore quoted segments exactly
    text = restore_quotes(text)

    return text
