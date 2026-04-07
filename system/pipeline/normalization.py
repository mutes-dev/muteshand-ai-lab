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

    text = text.lower().strip()

    NOISE_WORDS = ["please", "hey", "can you", "what is"]

    # STEP 1: Iterative prefix removal (handles multiple noise words)
    changed = True
    while changed:
        changed = False
        for word in NOISE_WORDS:
            if text.startswith(word + " "):
                text = text[len(word) + 1:]
                changed = True

    # STEP 2: Trailing noise removal (single pass only)
    TRAILING_NOISE = ["please", "thanks"]

    for word in TRAILING_NOISE:
        if text.endswith(" " + word):
            text = text[:-(len(word) + 1)]

    # STEP 3: Whitespace normalization (final step)
    text = " ".join(text.split())

    return text
