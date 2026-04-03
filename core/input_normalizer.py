"""
Input Normalizer Module

PURPOSE:
    Cleans and normalizes user input BEFORE it reaches the planner.
    Removes noise and standardizes format without changing semantic meaning.

ARCHITECTURE ROLE:
    - Pre-processing layer: First step in the pipeline
    - Stateless: Pure function with no side effects
    - Deterministic: Same input always produces same output

LAYER RESPONSIBILITY:
    - Convert to lowercase for case-insensitive processing
    - Trim whitespace from start and end
    - Remove common leading politeness phrases
    - Filter noise tokens while preserving valid arguments
    - Preserve argument values and structure

USAGE:
    >>> normalize_input("Please add 2 and 3")
    "add 2 and 3"
    
    >>> normalize_input("please can you just read the file test.txt for me thanks")
    "read file test.txt"

CONSTRAINTS:
    - No regex (simple string operations only)
    - No NLP or semantic inference
    - No token merging
    - No reordering
    - Deterministic behavior only
"""


def normalize_input(text: str) -> str:
    """
    Normalize user input by cleaning noise and standardizing format.
    
    NORMALIZATION STEPS:
        1. Convert to lowercase (case-insensitive processing)
        2. Trim leading/trailing whitespace
        3. Remove common leading politeness phrases
        4. Tokenize and filter noise tokens
        5. Reconstruct filtered text
    
    PRESERVATION RULES:
        - Numeric arguments are NOT modified (int, float, negative)
        - File-like tokens preserved (contains '.')
        - Path-like tokens preserved (contains '/' or '\')
        - URLs preserved (starts with http:// or https://)
        - PREVIOUS_RESULT preserved (special token)
        - Word order is preserved
        - Valid identifiers preserved (not in noise list)
    
    Args:
        text (str): Raw user input string
        
    Returns:
        str: Normalized input string
        
    Examples:
        >>> normalize_input("please can you just read the file test.txt for me thanks")
        "read file test.txt"
        
        >>> normalize_input("hey bro add 2 and 3 quickly")
        "add 2 and 3"
        
        >>> normalize_input("add x and y")
        "add x and y"
        
        >>> normalize_input("please read webpage https://example.com for me")
        "read webpage https://example.com"
        
        >>> normalize_input("add please 2 and 3")
        "add 2 and 3"
    """
    
    # STEP 1 — LOWERCASE
    # Convert entire input to lowercase for case-insensitive processing
    text = text.lower()
    
    # STEP 2 — TRIM
    # Remove leading and trailing whitespace
    text = text.strip()
    
    # STEP 3 — REMOVE SIMPLE LEADING PHRASES
    # Only remove phrases at the START of input (not embedded)
    LEADING_PHRASES = [
        "please ",
        "can you ",
        "could you ",
        "would you ",
        "hey ",
        "hi ",
    ]
    
    for phrase in LEADING_PHRASES:
        if text.startswith(phrase):
            text = text[len(phrase):]
            # Only remove first match, then break
            # This prevents removing multiple leading phrases
            break
    
    # STEP 4 — TOKENIZE
    tokens = text.split()
    
    # NOISE TOKENS — Known safe-to-remove words
    NOISE_TOKENS = {
        "please",
        "just",
        "maybe",
        "kindly",
        "quickly",
        "really",
        "like",
        "thanks",
        "thank",
        "you",
        "for",
        "me",
        "can",
        "could",
        "would",
        "hey",
        "hi",
        "bro",
    }
    
    # STEP 5 — TOKEN PROTECTION FUNCTION
    # Guarantees that valid arguments are NEVER removed
    def is_protected_token(token: str) -> bool:
        """
        Determine if a token is protected from noise filtering.
        
        PROTECTION RULES (in priority order):
            1. Numeric values (int, float, negative)
            2. File/path-like tokens (contains '.', '/', or '\')
            3. URLs (starts with http:// or https://)
            4. PREVIOUS_RESULT (special runtime token)
            5. Safe identifiers (alphanumeric, length ≤ 32)
        
        These tokens are NEVER removed, regardless of input complexity.
        
        Args:
            token (str): Token to check for protection
            
        Returns:
            bool: True if token is protected, False otherwise
        """
        # RULE 1 — Numeric (int/float/negative)
        if token.replace('.', '', 1).replace('-', '', 1).isdigit():
            return True
        
        # RULE 2 — Contains argument characters (file/path-like)
        if '.' in token or '/' in token or '\\' in token:
            return True
        
        # RULE 3 — URL
        if token.startswith("http://") or token.startswith("https://"):
            return True
        
        # RULE 4 — PREVIOUS_RESULT
        if token == "PREVIOUS_RESULT":
            return True
        
        # RULE 5 — IDENTIFIER (SAFE SHAPE)
        if token.isalnum() and len(token) <= 32:
            return True
        
        return False
    
    # STEP 6 — APPLY FILTER (MANDATORY PROTECTION ORDER)
    # Priority: Protected tokens first, then noise filtering
    filtered_tokens = []
    
    for token in tokens:
        if is_protected_token(token):
            # Protected tokens are ALWAYS preserved
            filtered_tokens.append(token)
        elif token not in NOISE_TOKENS:
            # Non-protected, non-noise tokens are preserved
            filtered_tokens.append(token)
        # else: token is noise and not protected → removed
    
    # STEP 7 — RECONSTRUCT
    text = " ".join(filtered_tokens)
    
    return text
