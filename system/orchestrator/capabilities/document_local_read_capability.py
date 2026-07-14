"""Document Local Read Capability — Deterministic read-only file/folder detector/compiler.

Per AGENT_CAPABILITY_ROUTING_CONTRACT_V1 Section 10A:
- High-confidence explicit local-file read/list/summarize/explain detection only
- No LLM. No system_entry import. No execution.
- Emits explicit candidate workflow/DAG with depends_on.
- Fallback for ambiguous, mutation, mixed-domain, grep/glob, multi-file, unsupported final actions.

Supported deterministic DAG shapes:
- read_file -> finalize_output  (present mode)
- read_file -> finalize_output  (summarize/explain/extract_key_points mode)
- list_files -> finalize_output  (present mode)
- No grep/glob/multi-file.
"""

import os
import re
from typing import Any

from system.orchestrator.capabilities.document_intake_resolver import resolve_document_tool


# === Mutation detection — conservative fallback keywords ===
_MUTATION_KEYWORDS = frozenset([
    "write", "edit", "append", "delete", "remove", "erase", "create file",
    "save", "update", "modify", "overwrite", "replace file",
])

# === Mixed-domain detection — conservative fallback keywords ===
_MIXED_DOMAIN_KEYWORDS = frozenset([
    "web", "website", "url", "http", "https", "internet", "browse",
    "download", "upload", "email", "send mail", "calendar", "schedule",
    "api", "external", "search the web", "google", "online",
    "add ", "plus ", "subtract ", "minus ", "multiply ", "divide ",
    "square root", "factorial", "fibonacci",
    "learn", "remember", "index", "store",
    "find more info", "find more information",
    "search for more", "search for related",
])

# === Grep/glob/search detection — first-slice fallback ===
_GREP_GLOB_KEYWORDS = frozenset([
    "grep", "search for", "search within", "find pattern", "match pattern",
    "glob", "match files", "find all files", "list matching", "files matching",
    "search in", "search files for", "regex", "regular expression",
    "find all", "all .py", "all .txt", "all .json", "all .md",
])

# === Read-file intent patterns ===
# Each entry: (regex, has_path_group: bool)
# Ordered by specificity (most specific first).
_READ_FILE_PATTERNS = [
    # OCR/scanned image read patterns
    (re.compile(r'(?:ocr)\s+(?:the\s+)?(?:scanned\s+)?(?:pdf\s+)?(?:image\s+)?(?:file\s+)?["\']([^"\']+)["\']', re.IGNORECASE), True),
    (re.compile(r'(?:read)\s+(?:text\s+from\s+)?(?:scanned\s+)?(?:image\s+)?["\']([^"\']+)["\']', re.IGNORECASE), True),
    (re.compile(r'(?:extract)\s+(?:text\s+from\s+)?(?:scanned\s+)?(?:image\s+)?["\']([^"\']+)["\']', re.IGNORECASE), True),
    # Read/show/open/display the CSV/spreadsheet/DOCX "path" / 'path'
    (re.compile(r'(?:read|show|open|display|view)\s+(?:the\s+)?(?:csv|spreadsheet|xlsx|docx)\s+["\']([^"\']+)["\']', re.IGNORECASE), True),
    # Read/show/open/display the file "path" / 'path'
    (re.compile(r'(?:read|show|open|display|view)\s+(?:the\s+)?(?:file\s+)?["\']([^"\']+)["\']', re.IGNORECASE), True),
    # Read/show/open/display file "path" / 'path'
    (re.compile(r'(?:read|show|open|display|view)\s+(?:the\s+)?(?:contents\s+of\s+)?["\']([^"\']+)["\']', re.IGNORECASE), True),
    # Read/show/open/display path (unquoted, with extension)
    # Handles: "Show me the contents of config.json", "Read tmp/file.txt", "Read E:\MutesHand\tmp\Quoted File Name.txt"
    # Also handles simple filenames like "README.md" but avoids domain names like "example.com"
    # Requires path separators, drive letter, or simple filename (but not common domain patterns)
    (re.compile(r'(?:read|show|open|display|view|ocr|extract)\s+(?:me\s+)?(?:the\s+)?(?:contents\s+of\s+)?(?:file\s+)?(?:text\s+from\s+)?(?:scanned\s+)?(?:image\s+)?([a-zA-Z0-9_./\\~ -]*[\\/][a-zA-Z0-9_./\\~ -]*\.[a-zA-Z0-9]{1,10}|[a-zA-Z]:[\\/][a-zA-Z0-9_./\\~ -]*\.[a-zA-Z0-9]{1,10}|[a-zA-Z0-9_ -]*\.(?:config|json|yaml|yml|xml|txt|md|py|js|csv|log|ini|cfg|conf|pdf|docx|xlsx|png|jpg|jpeg))', re.IGNORECASE), True),
]

# === List-files intent patterns ===
_LIST_FILES_PATTERNS = [
    # List files in "folder" / 'folder'
    (re.compile(r'(?:list|show)\s+(?:the\s+)?(?:files\s+in|contents\s+of|files\s+inside)\s+["\']([^"\']+)["\']', re.IGNORECASE), True),
    # List files in the folder "folder" / 'folder'
    (re.compile(r'(?:list|show)\s+(?:the\s+)?(?:files\s+in|contents\s+of|files\s+inside)\s+(?:the\s+(?:folder|directory)\s+)?["\']([^"\']+)["\']', re.IGNORECASE), True),
    # List files in the folder X (unquoted)
    # Requires path separators, drive letter, or simple folder name to avoid matching domain names
    (re.compile(r'(?:list|show)\s+(?:the\s+)?(?:files\s+in|contents\s+of|files\s+inside)\s+(?:the\s+(?:folder|directory)\s+)?([a-zA-Z0-9_./\\~ -]*[\\/][a-zA-Z0-9_./\\~ -]*|[a-zA-Z]:[\\/][a-zA-Z0-9_./\\~ -]*|[a-zA-Z0-9_ -]+)', re.IGNORECASE), True),
    # List the folder "folder"
    (re.compile(r'(?:list|show)\s+(?:the\s+)?(?:folder|directory)\s+["\']([^"\']+)["\']', re.IGNORECASE), True),
    # List the folder X (unquoted)
    # Requires path separators, drive letter, or simple folder name to avoid matching domain names
    (re.compile(r'(?:list|show)\s+(?:the\s+)?(?:folder|directory)\s+([a-zA-Z0-9_./\\~ -]*[\\/][a-zA-Z0-9_./\\~ -]*|[a-zA-Z]:[\\/][a-zA-Z0-9_./\\~ -]*|[a-zA-Z0-9_ -]+)', re.IGNORECASE), True),
    # Files in "folder"
    (re.compile(r'(?:files|contents)\s+(?:in|inside|of)\s+["\']([^"\']+)["\']', re.IGNORECASE), True),
    # Files in the folder X (unquoted)
    # Requires path separators or drive letter to avoid matching domain names
    (re.compile(r'(?:files|contents)\s+(?:in|inside|of)\s+(?:the\s+(?:folder|directory)\s+)?([a-zA-Z0-9_./\\~ -]*[\\/][a-zA-Z0-9_./\\~ -]*|[a-zA-Z]:[\\/][a-zA-Z0-9_./\\~ -]*)', re.IGNORECASE), True),
]

# === F2B-1 table reference / schema preview intent patterns ===
# Multiple patterns are tried in order to support both explicit command phrasing
# and natural-language phrasing while keeping each regex bounded and readable.
_PREVIEW_TABLE_SCHEMA_PATTERNS = [
    # "Preview the table schema for ..." / "Preview the schema of ..."
    re.compile(
        r'\bpreview\s+(?:the\s+)?(?:table\s+)?schema\s+(?:for|of)\s+["\']?([^"\']+?\.(?:csv|xlsx|xls))["\']?\b',
        re.IGNORECASE,
    ),
    # "Show me the schema of the CSV file at ..."
    re.compile(
        r'\bshow\s+(?:me\s+)?(?:the\s+)?schema\s+(?:for|of)\s+(?:the\s+)?(?:csv\s+)?file\s+at\s+["\']?([^"\']+?\.(?:csv|xlsx|xls))["\']?\b',
        re.IGNORECASE,
    ),
    # "What is the schema of the CSV file at ..."
    re.compile(
        r'\bwhat\s+is\s+(?:the\s+)?schema\s+(?:for|of)\s+(?:the\s+)?(?:csv\s+)?file\s+at\s+["\']?([^"\']+?\.(?:csv|xlsx|xls))["\']?\b',
        re.IGNORECASE,
    ),
    # "Show me the schema of ..." / "What is the schema of ..."
    re.compile(
        r'\b(?:show\s+(?:me\s+)?|what\s+is\s+(?:the\s+)?)(?:the\s+)?schema\s+(?:for|of)\s+["\']?([^"\']+?\.(?:csv|xlsx|xls))["\']?\b',
        re.IGNORECASE,
    ),
    # "CSV schema for ..." / "Table schema of ..." / "Spreadsheet schema of ..."
    re.compile(
        r'\b(?:csv|table|spreadsheet)\s+schema\s+(?:for|of)\s+["\']?([^"\']+?\.(?:csv|xlsx|xls))["\']?\b',
        re.IGNORECASE,
    ),
]

_RESOLVE_TABLE_CELL_PATTERNS = [
    # Explicit: "Resolve cell B2 from/in ..."
    re.compile(
        r'\bresolve\s+(?:cell\s+)?([A-Za-z]\d+)\s+(?:from|in|of)\s+["\']?([^"\']+?\.(?:csv|xlsx|xls))["\']?\b',
        re.IGNORECASE,
    ),
    # Natural: "What is the value in cell B2 of ...?" / "What is cell B2 in ...?"
    #          "Value in cell B2 of ..."
    re.compile(
        r'\b(?:what\s+(?:is\s+(?:the\s+)?)?)?value\s+(?:in\s+)?cell\s+([A-Za-z]\d+)\s+(?:in|of|from)\s+["\']?([^"\']+?\.(?:csv|xlsx|xls))["\']?\b',
        re.IGNORECASE,
    ),
    # Short: "What is cell B2 of ...?"
    re.compile(
        r'\bwhat\s+is\s+cell\s+([A-Za-z]\d+)\s+(?:in|of|from)\s+["\']?([^"\']+?\.(?:csv|xlsx|xls))["\']?\b',
        re.IGNORECASE,
    ),
]

_RESOLVE_TABLE_ROW_PATTERNS = [
    # Explicit: "Resolve row 3 from/in ..."
    re.compile(
        r'\bresolve\s+(?:row\s+)?(\d+)\s+(?:from|in|of)\s+["\']?([^"\']+?\.(?:csv|xlsx|xls))["\']?\b',
        re.IGNORECASE,
    ),
    # Natural: "What is in row 3 of ...?" / "Show row 3 from ..."
    re.compile(
        r'\b(?:what\s+is\s+(?:in\s+)?|show\s+)row\s+(\d+)\s+(?:of|from|in)\s+["\']?([^"\']+?\.(?:csv|xlsx|xls))["\']?\b',
        re.IGNORECASE,
    ),
]

_ENTITY_FROM_ROW_PATTERNS = [
    # "Who is in row 4 in the Name column of ...?"
    # capture order: (row_number, entity_column, file_path)
    (
        re.compile(
            r'\b(?:who|what)\s+(?:is\s+|are\s+)?(?:the\s+)?(?:value\s+)?(?:is\s+|are\s+)?in\s+row\s+(\d+)\s+(?:in\s+)?(?:the\s+)?([A-Za-z][A-Za-z0-9_]*?)\s*(?:column\s*)?(?:of|from|in)\s+["\']?([^"\']+?\.(?:csv|xlsx|xls))["\']?\b',
            re.IGNORECASE,
        ),
        "row_entity",
    ),
    # "What is the Name in row 4 of ...?"
    # capture order: (entity_column, row_number, file_path)
    (
        re.compile(
            r'\b(?:who|what)\s+is\s+(?:the\s+)?([A-Za-z][A-Za-z0-9_]*?)\s+in\s+row\s+(\d+)\s+(?:of|from|in)\s+["\']?([^"\']+?\.(?:csv|xlsx|xls))["\']?\b',
            re.IGNORECASE,
        ),
        "entity_row",
    ),
    # "Value in row 4 column Name from ..."
    # capture order: (row_number, entity_column, file_path)
    (
        re.compile(
            r'\bvalue\s+in\s+row\s+(\d+)\s+(?:column\s+)?([A-Za-z][A-Za-z0-9_]*?)\s+(?:of|from|in)\s+["\']?([^"\']+?\.(?:csv|xlsx|xls))["\']?\b',
            re.IGNORECASE,
        ),
        "row_entity",
    ),
]

# === F2B-2 generic ordinal / shorthand table-reference parsing ===
_ORDINAL_WORDS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
    "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5,
    "6th": 6, "7th": 7, "8th": 8, "9th": 9, "10th": 10,
}
_ORDINAL_WORDS_LOWER = {k.lower(): v for k, v in _ORDINAL_WORDS.items()}
_ORDINAL_TOKEN_RE = r"first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|1st|2nd|3rd|4th|5th|6th|7th|8th|9th|10th|\d+(?:st|nd|rd|th)"

# Column name token used in shorthand extraction (e.g., Name, Score, Team).
_COLUMN_NAME_RE = r"[A-Za-z][A-Za-z0-9_]*"

# Header ordinal: "third header column", "column 3 header", "what is the third header"
_HEADER_ORDINAL_PATTERNS = [
    re.compile(
        rf'\b(?P<ord>{_ORDINAL_TOKEN_RE})\s+(?:header\s+column|column\s+header|header)\b',
        re.IGNORECASE,
    ),
    re.compile(
        rf'\bcolumn\s+(?P<card>\d+)\s+(?:header|name)\b',
        re.IGNORECASE,
    ),
    re.compile(
        rf'\bwhat\s+(?:is\s+)?(?:the\s+)?(?P<ord>{_ORDINAL_TOKEN_RE})\s+header\b',
        re.IGNORECASE,
    ),
]

# Row + column shorthand: "row 3 name", "column Score row 2",
# "value in the Name column for row 3", "value in row 3 Name column"
_ROW_COLUMN_SHORTHAND_PATTERNS = [
    re.compile(
        rf'\brow\s+(?P<row>\d+)\s+(?P<col>{_COLUMN_NAME_RE})\b',
        re.IGNORECASE,
    ),
    re.compile(
        rf'\bcolumn\s+(?P<col>{_COLUMN_NAME_RE})\s+row\s+(?P<row>\d+)\b',
        re.IGNORECASE,
    ),
    re.compile(
        rf'\b(?P<col>{_COLUMN_NAME_RE})\s+(?:column\s+)?row\s+(?P<row>\d+)\b',
        re.IGNORECASE,
    ),
    re.compile(
        rf'\bvalue\s+(?:in|of|from)\s+(?:the\s+)?(?P<col>{_COLUMN_NAME_RE})\s+(?:column\s+)?(?:for|of|in)?\s+row\s+(?P<row>\d+)\b',
        re.IGNORECASE,
    ),
    re.compile(
        rf'\bvalue\s+(?:in|of|from)\s+row\s+(?P<row>\d+)\s+(?:in|of)?\s+(?:the\s+)?(?P<col>{_COLUMN_NAME_RE})\s+(?:column\b)?',
        re.IGNORECASE,
    ),
]

# Ordinal value in a named column: "third value in Name column", "3rd value in Score"
# The column name must not be followed by a path separator (avoid matching a path segment).
_VALUE_IN_COLUMN_ORDINAL_PATTERNS = [
    re.compile(
        rf'\b(?P<ord>{_ORDINAL_TOKEN_RE})\s+(?:value|item|entry)\s+(?:in|of|from)\s+(?:the\s+)?(?P<col>{_COLUMN_NAME_RE})(?!\s*[\\/])\s+(?:column\b)?',
        re.IGNORECASE,
    ),
    re.compile(
        rf'\b(?P<ord>{_ORDINAL_TOKEN_RE})\s+(?:value|item|entry)\s+(?:in|of|from)\s+(?:the\s+)?(?P<col>{_COLUMN_NAME_RE})(?!\s*[\\/])\b',
        re.IGNORECASE,
    ),
]

# Name-like column ordinal: "third name", "3rd person", "2nd user".
# The unique name-like column is resolved at the tool level, not hardcoded.
_NAME_LIKE_ORDINAL_PATTERNS = [
    re.compile(
        rf'\b(?P<ord>{_ORDINAL_TOKEN_RE})\s+(?:name|names|person|people|user|users)\b',
        re.IGNORECASE,
    ),
]

# Ordinal row: "second row", "3rd row".
_ORDINAL_ROW_PATTERNS = [
    re.compile(
        rf'\b(?P<ord>{_ORDINAL_TOKEN_RE})\s+row\b',
        re.IGNORECASE,
    ),
    re.compile(
        rf'\brow\s+(?P<ord>{_ORDINAL_TOKEN_RE})\b',
        re.IGNORECASE,
    ),
]

# Generic table-reference intent detector for the false-success guard.
# Matches ordinals or row/column/header/cell keywords, but not standalone words
# that appear in numeric analysis prompts (e.g. "score", "highest", "sum").
_TABLE_REFERENCE_INTENT_RE = re.compile(
    rf'\b(?:{_ORDINAL_TOKEN_RE})\b|'
    r'\b(?:row|column|header|cell)\b',
    re.IGNORECASE,
)

# Sentinel used when a unique name-like column must be discovered at runtime.
_AUTO_NAME_LIKE_COLUMN = "__AUTO_NAME_LIKE__"

# Matches a CSV/XLSX/XLS path whether quoted or unquoted. Used only for
# deterministic unsupported-spreadsheet-analysis guard and fallback-reason
# accuracy; it does not route to read_file.
_CSV_XLSX_PATH_RE = re.compile(
    r'["\']([^"\']+?\.(?:csv|xlsx|xls))["\']|'
    r'(?<![a-zA-Z0-9_./\\~\-])([a-zA-Z0-9_./\\~\-]*[\\/][a-zA-Z0-9_./\\~\-]*\.(?:csv|xlsx|xls)|'
    r'[a-zA-Z0-9_\-]*\.(?:csv|xlsx|xls))',
    re.IGNORECASE,
)

# === Vague/ambiguous fallback patterns ===
_AMBIGUOUS_FILE_REFERENCES = frozenset([
    "the file", "that file", "this file", "a file", "some file",
])

# === Supported transform actions ===
# These are handled by explicit transform workflows, not by unsupported fallback.
_TRANSFORM_FILE_ACTIONS = {
    "summarize": re.compile(
        r"\b(?:summarize|summarise|summary\s+of|give\s+me\s+a\s+summary\s+of)\b",
        re.IGNORECASE,
    ),
    "explain": re.compile(
        r"\b(?:explain|explain\s+what\s+is\s+in)\b",
        re.IGNORECASE,
    ),
    "extract_key_points": re.compile(
        r"\b(?:extract\s+key\s+points\s+from)\b",
        re.IGNORECASE,
    ),
}

# === Unsupported final action detection ===
# compare/analyze/fact-check remain deferred; summarize/explain/extract are now supported.
_UNSUPPORTED_FINAL_ACTION_RE = re.compile(
    r"\b(?:compare|comparison\s+of|analyze|analyse|analysis\s+of|fact-check|fact\s+check)\b",
    re.IGNORECASE,
)

# === Supported tail transforms after read/show/open (e.g. "read X and summarize it") ===
_TAIL_TRANSFORM_RE = re.compile(
    r"\b(?:and|then)\s+(?:summarize|summarise|summary\s+of|explain|extract\s+key\s+points)\b",
    re.IGNORECASE,
)

# === Q&A intent patterns (single-document answer_question) ===
# Each entry captures: (file_path_group, question_group)
_QUESTION_WORDS = r"(?:what|who|when|where|why|how|which|is|are|does|do|did|can)"
_QA_FILE_PATTERNS = [
    # answer this question from "<path>": <question>
    # answer this question from "<path>" <question>
    re.compile(
        rf'answer\s+(?:this\s+)?question\s+from\s+["\']([^"\']+?)["\']\s*:\s*(.+)',
        re.IGNORECASE,
    ),
    re.compile(
        rf'answer\s+(?:this\s+)?question\s+from\s+["\']([^"\']+?)["\']\s+({_QUESTION_WORDS})\b(.+)?',
        re.IGNORECASE,
    ),
    # answer from "<path>": <question>
    # answer from "<path>" <question>
    re.compile(
        rf'answer\s+from\s+["\']([^"\']+?)["\']\s*:\s*(.+)',
        re.IGNORECASE,
    ),
    re.compile(
        rf'answer\s+from\s+["\']([^"\']+?)["\']\s+({_QUESTION_WORDS})\b(.+)?',
        re.IGNORECASE,
    ),
    # from "<path>", <question>
    re.compile(
        rf'from\s+["\']([^"\']+?)["\']\s*,\s*(.+)',
        re.IGNORECASE,
    ),
    # from "<path>" <question>
    re.compile(
        rf'from\s+["\']([^"\']+?)["\']\s+({_QUESTION_WORDS})\b(.+)?',
        re.IGNORECASE,
    ),
    # from the file "<path>", <question>
    re.compile(
        rf'from\s+(?:the\s+)?file\s+["\']([^"\']+?)["\']\s*,\s*(.+)',
        re.IGNORECASE,
    ),
    # from the file "<path>" <question>
    re.compile(
        rf'from\s+(?:the\s+)?file\s+["\']([^"\']+?)["\']\s+({_QUESTION_WORDS})\b(.+)?',
        re.IGNORECASE,
    ),
    # read the file "<path>" and tell me <question>
    re.compile(
        rf'read\s+(?:the\s+)?file\s+["\']([^"\']+?)["\']\s+(?:and|then)\s+tell\s+me\s+(.+)',
        re.IGNORECASE,
    ),
    # read "<path>" and tell me <question>
    re.compile(
        rf'read\s+["\']([^"\']+?)["\']\s+(?:and|then)\s+tell\s+me\s+(.+)',
        re.IGNORECASE,
    ),
    # read the file "<path>" <question>
    re.compile(
        rf'read\s+(?:the\s+)?file\s+["\']([^"\']+?)["\']\s+({_QUESTION_WORDS})\b(.+)?',
        re.IGNORECASE,
    ),
    # read "<path>" <question>
    re.compile(
        rf'read\s+["\']([^"\']+?)["\']\s+({_QUESTION_WORDS})\b(.+)?',
        re.IGNORECASE,
    ),
]

# === CSV/XLSX analysis keywords beyond bounded F5A scope ===
# Regex with word boundaries so "sum" does not match inside "summarize" and
# "max" does not match inside "maximum".
_CSV_XLSX_ANALYSIS_KEYWORDS_RE = re.compile(
    r"\b(?:highest|lowest|average|mean|sum|total|count|calculate|formula|"
    r"compare\s+rows|sort|filter|rank|maximum|minimum|max|min|median|mode|"
    r"standard\s+deviation|aggregate|score|scores|column|row|rows|top|bottom|"
    r"group\b.*\bby\b|analyze)\b",
    re.IGNORECASE,
)

# === Static unsupported messages for CSV/XLSX analysis beyond current F5A scope ===
_UNSUPPORTED_SPREADSHEET_ANALYSIS_MESSAGE = (
    "Open-ended CSV/XLSX analysis is not supported by the current bounded implementation. "
    "Supported operations are row count, minimum, maximum, sum, average, "
    "associated-row or entity results for minimum and maximum, and table overview. "
    "Filtering, sorting, ranking, grouped analysis, and composed operations remain "
    "part of the open F5 implementation package."
)

_SEMANTIC_ANALYSIS_UNSUPPORTED_MESSAGE = (
    "Deterministic table structure and basic statistics are supported, but this "
    "request requires interpretation or semantic reasoning that is not part of the "
    "current structured-data analysis scope. Ask for a table overview, row count, "
    "minimum, maximum, sum, average, or associated-row result."
)

# Keywords that turn an "analyze ..." prompt into a semantic/interpretive unsupported
# request rather than a bounded table overview.
_SEMANTIC_ANALYSIS_KEYWORDS = frozenset([
    "why", "reason", "reasons", "meaning", "means", "explain why",
    "insight", "insights", "interesting", "pattern", "patterns",
    "predict", "prediction", "forecast", "recommend", "recommendation",
    "business decision", "business decisions", "decision",
    "cause", "causes", "causal", "trend", "trends",
    "unusual", "anomaly", "anomalies", "relationship", "relationships",
    "interpret", "interpretation", "implication", "implications", "significance",
])

# Bounded overview phrases that should route to structured_data_analysis instead of
# being captured by the unsupported-spreadsheet-analysis guard.
_BOUNDED_OVERVIEW_RE = re.compile(
    r"\b(?:analyze|analyse)\b(?:\s+(?:the\s+)?(?:table|file|data|spreadsheet))?(?:\s+in)?|"
    r"\b(?:give me an |show (?:me )?|get an |provide an )?overview of\b|"
    r"\bbasic statistics for\b|"
    r"\bsummarize the table structure and basic statistics\b|"
    r"\btable overview\b",
    re.IGNORECASE,
)

# === Question tail detection — prevents silent read/present downgrade ===
_QUESTION_TAIL_RE = re.compile(
    rf'(?:read|show|open|view)\s+(?:the\s+)?(?:file\s+)?["\']([^"\']+?)["\']\s+(?:and|then)?\s*({_QUESTION_WORDS})\b',
    re.IGNORECASE,
)

# === Unsupported tail intent after read/show/open (e.g. "read X and tell me...") ===
_TAIL_INTENT_REJECT_RE = re.compile(
    r"\b(?:and|then|also)\s+(?:tell\s+me|answer|find|what\s+(?:is|are)|how\s+(?:big|much|many|long))\b",
    re.IGNORECASE,
)


# === File-prompt heuristic for router fallback labeling ===
_FILE_PROMPT_TOKENS = frozenset([
    "file", "folder", "directory", "read the file", "show the file",
    "open the file", "display the file", "view the file", "list files",
    "show files", "files in", "contents of", "list the folder",
    "show the folder", "list the directory", "show the directory",
    ".txt", ".md", ".json", ".py", ".csv", ".log", ".xml", ".yml", ".yaml",
    ".pdf", ".docx", ".xlsx", ".png", ".jpg", ".jpeg",
    "image", "ocr", "extract text from",
])


def _is_file_mutation(text: str) -> bool:
    """Return True if prompt contains file mutation keywords."""
    lower = text.lower()
    return any(kw in lower for kw in _MUTATION_KEYWORDS)


def _is_mixed_domain(text: str) -> bool:
    """Return True if prompt contains mixed-domain keywords."""
    lower = text.lower()
    return any(kw in lower for kw in _MIXED_DOMAIN_KEYWORDS)


def _is_grep_glob_request(text: str) -> bool:
    """Return True if prompt asks for grep/glob/search within files (first-slice fallback)."""
    lower = text.lower()
    return any(kw in lower for kw in _GREP_GLOB_KEYWORDS)


def _is_ambiguous_file_reference(text: str) -> bool:
    """Return True if prompt contains vague file references without explicit path."""
    lower = text.lower()
    # Only trigger if ambiguous phrase exists AND no explicit path with extension found
    has_ambiguous = any(kw in lower for kw in _AMBIGUOUS_FILE_REFERENCES)
    if not has_ambiguous:
        return False
    # Check if an explicit file path with extension exists
    # Requires path separators, drive letter, or simple filename (but not common domain patterns)
    has_explicit_path = bool(re.search(r'[a-zA-Z0-9_./\\~ -]*[\\/][a-zA-Z0-9_./\\~ -]*\.[a-zA-Z0-9]{1,10}|[a-zA-Z]:[\\/][a-zA-Z0-9_./\\~ -]*\.[a-zA-Z0-9]{1,10}|[a-zA-Z0-9_ -]*\.(?:config|json|yaml|yml|xml|txt|md|py|js|csv|log|ini|cfg|conf|pdf|docx|xlsx|png|jpg|jpeg)', text))
    # Also consider any quoted path as explicit (supports extensionless quoted paths)
    has_quoted_path = bool(re.search(r'["\']([^"\']+)["\']', text))
    return not has_explicit_path and not has_quoted_path


def _has_unsupported_final_action(text: str) -> bool:
    return bool(_UNSUPPORTED_FINAL_ACTION_RE.search(text))


def _unsupported_final_action_reason(text: str) -> str:
    return "fallback_unsupported_final_action"


def _detect_tail_transform(text: str) -> str | None:
    """Return supported transform action if prompt has a tail transform after read/show/open."""
    lower = text.lower()
    if re.search(r"\b(?:and|then)\s+(?:summarize|summarise|summary\s+of)\b", lower):
        return "summarize"
    if re.search(r"\b(?:and|then)\s+explain\b", lower):
        return "explain"
    if re.search(r"\b(?:and|then)\s+extract\s+key\s+points\b", lower):
        return "extract_key_points"
    return None


def _has_unsupported_tail_intent(text: str) -> bool:
    """Return True if prompt contains unsupported tail intent after a file reference."""
    return bool(_TAIL_INTENT_REJECT_RE.search(text))


def _detect_qa_intent(text: str) -> tuple[str, str] | None:
    """Extract (file_path, question) from a Q&A intent prompt, or None if no match.

    Patterns with a question-word group reconstruct the question from the captured
    groups so the question always includes the leading word.
    """
    for pattern in _QA_FILE_PATTERNS:
        m = pattern.search(text)
        if m:
            path = m.group(1).strip()
            if not path:
                continue
            if len(m.groups()) == 2:
                question = m.group(2).strip()
            else:
                # 3 groups: question_word + rest (may be None)
                q_word = m.group(2).strip()
                q_rest = (m.group(3) or "").strip()
                question = f"{q_word} {q_rest}".strip() if q_rest else q_word
            if question:
                return (path, question)
    return None


def _is_csv_xlsx(path: str) -> bool:
    """Return True if path is CSV or XLSX."""
    lower = path.lower()
    return lower.endswith(".csv") or lower.endswith(".xlsx")


def _has_csv_xlsx_analysis_intent(text: str) -> bool:
    """Return True if prompt contains CSV/XLSX numeric/data-analysis keywords."""
    return bool(_CSV_XLSX_ANALYSIS_KEYWORDS_RE.search(text))


def _has_multiple_paths(text: str) -> bool:
    """Return True if prompt contains more than one quoted path.

    Single-document Q&A must reference exactly one concrete file.
    """
    quoted_paths = re.findall(r'["\']([^"\']+?\.[a-zA-Z0-9]{1,10})["\']', text)
    return len(quoted_paths) > 1


def _has_multiple_questions(question: str) -> bool:
    """Return True if question appears to contain multiple distinct questions.

    Conservative: multiple question marks or a question word after 'and'/'or'.
    """
    q_lower = question.lower()
    question_count = question.count("?")
    if question_count > 1:
        return True
    if re.search(r'\b(?:and|or)\s+(?:what|who|when|where|why|how|which|is|are|does|do|did|can)\b', q_lower):
        return True
    return False


def _has_question_about_file_tail(text: str) -> bool:
    """Detect a read/show/open + quoted path + question tail not caught by Q&A patterns.

    This prevents silent read/present downgrade for prompts like:
    'Read the file "tmp/report.pdf" what is this document about?'
    """
    return bool(_QUESTION_TAIL_RE.search(text))


# === OCR intent detection for scanned PDF routing ===
_OCR_KEYWORDS = frozenset([
    "ocr", "scanned", "scan", "image-only", "image only",
    "read text from scanned", "extract text from scanned",
])


def _is_ocr_intent(text: str) -> bool:
    """Return True if prompt contains explicit OCR/scanned PDF intent."""
    lower = text.lower()
    return any(kw in lower for kw in _OCR_KEYWORDS)


def _resolve_acquisition_tool(file_path: str, user_input: str = "") -> str | None:
    """Map file path to the appropriate acquisition tool using resolver."""
    result = resolve_document_tool(file_path, user_input)
    tool = result.get("tool")
    if tool:
        return tool
    # Preserve original behavior: unknown explicit extension -> read_file
    lower = file_path.lower()
    basename = os.path.basename(lower)
    if "." in basename:
        return "read_file"
    # Extensionless unknown -> None (planner fallback)
    return None


def _detect_transform_file_action(text: str) -> str | None:
    """Return supported transform action (summarize/explain/extract_key_points) if present."""
    for action, pattern in _TRANSFORM_FILE_ACTIONS.items():
        if pattern.search(text):
            return action
    return None


def _extract_transform_file_path(text: str, action: str) -> str | None:
    """Extract explicit file path from a transform-intent prompt for the given action."""
    if action not in _TRANSFORM_FILE_ACTIONS:
        return None
    verb_pattern = _TRANSFORM_FILE_ACTIONS[action].pattern
    # Quoted path
    quoted = re.compile(
        rf"(?:{verb_pattern})\s+(?:the\s+)?(?:scanned\s+)?(?:pdf\s+)?(?:image\s+)?(?:file\s+)?[\"\']([^\"\']+)[\"\']",
        re.IGNORECASE,
    )
    m = quoted.search(text)
    if m:
        path = m.group(1).strip()
        if path:
            return path
    # Unquoted path with extension
    # Requires path separators, drive letter, or simple filename (but not common domain patterns)
    unquoted_pattern = f"(?:{verb_pattern})\\s+(?:the\\s+)?(?:file\\s+)?([a-zA-Z0-9_./\\\\~ -]*[\\\\/][a-zA-Z0-9_./\\\\~ -]*\\.[a-zA-Z0-9]{{1,10}}|[a-zA-Z]:[\\\\/][a-zA-Z0-9_./\\\\~ -]*\\.[a-zA-Z0-9]{{1,10}}|[a-zA-Z0-9_ -]*\\.(?:config|json|yaml|yml|xml|txt|md|py|js|csv|log|ini|cfg|conf|pdf|docx|xlsx|png|jpg|jpeg))"
    unquoted = re.compile(unquoted_pattern, re.IGNORECASE)
    m = unquoted.search(text)
    if m:
        path = m.group(1).strip()
        if path:
            return path
    return None


def is_document_local_prompt(user_input: str) -> bool:
    """Return True if prompt is plausibly local-file-related (for router fallback labeling)."""
    if not user_input or not isinstance(user_input, str):
        return False
    lower = user_input.lower()
    return any(kw in lower for kw in _FILE_PROMPT_TOKENS)


def detect_document_local_read_fallback_reason(user_input: str) -> str:
    """Return a specific fallback reason code for a non-routed local-file prompt.

    This is advisory metadata only; the route decision remains the authority.
    """
    if not user_input or not isinstance(user_input, str):
        return "fallback_missing_explicit_file_path"

    if _is_file_mutation(user_input):
        return "fallback_unsupported_operation"

    if _is_mixed_domain(user_input):
        return "fallback_mixed_domain"

    if _is_grep_glob_request(user_input):
        return "fallback_grep_glob_not_supported"

    if _is_ambiguous_file_reference(user_input):
        return "fallback_ambiguous_file_reference"

    if _has_unsupported_final_action(user_input):
        return _unsupported_final_action_reason(user_input)

    if _has_unsupported_tail_intent(user_input):
        return "fallback_unsupported_tail_intent"

    if not _extract_read_file_path(user_input) and not _extract_list_files_folder(user_input):
        # If a CSV/XLSX path is present but the intent phrasing is unsupported,
        # report a more accurate reason than "missing explicit file path".
        if _extract_csv_xlsx_paths(user_input):
            return "fallback_no_supported_document_local_read_intent"
        return "fallback_missing_explicit_file_path"

    return "fallback_unsupported_operation"


def _extract_read_file_path(text: str) -> str | None:
    """Extract explicit file path from a read-file intent prompt."""
    for pattern, has_group in _READ_FILE_PATTERNS:
        m = pattern.search(text)
        if m and has_group:
            path = m.group(1).strip()
            if path:
                return path
    return None


def _extract_list_files_folder(text: str) -> str | None:
    """Extract explicit folder path from a list-files intent prompt."""
    for pattern, has_group in _LIST_FILES_PATTERNS:
        m = pattern.search(text)
        if m and has_group:
            path = m.group(1).strip()
            if path:
                return path
    return None


def _extract_preview_schema_path(text: str) -> str | None:
    """Extract file path from a preview-table-schema intent prompt."""
    for pattern in _PREVIEW_TABLE_SCHEMA_PATTERNS:
        m = pattern.search(text)
        if m:
            path = m.group(1).strip()
            if path:
                return path
    return None


def _extract_resolve_table_reference(text: str) -> dict | None:
    """Extract reference parameters from a resolve-table-reference intent prompt.

    Returns a dict with keys:
      - reference_type: "cell" | "row" | "entity_from_row"
      - file_path
      - cell_address (for cell)
      - row_number (for row/entity_from_row)
      - entity_column (for entity_from_row)
    """
    for pattern in _RESOLVE_TABLE_CELL_PATTERNS:
        m = pattern.search(text)
        if m:
            return {
                "reference_type": "cell",
                "cell_address": m.group(1).strip().upper(),
                "file_path": m.group(2).strip(),
            }

    for pattern in _RESOLVE_TABLE_ROW_PATTERNS:
        m = pattern.search(text)
        if m:
            return {
                "reference_type": "row",
                "row_number": int(m.group(1)),
                "file_path": m.group(2).strip(),
            }

    for pattern, group_order in _ENTITY_FROM_ROW_PATTERNS:
        m = pattern.search(text)
        if m:
            if group_order == "row_entity":
                row_number = int(m.group(1))
                entity_column = m.group(2).strip()
            else:
                entity_column = m.group(1).strip()
                row_number = int(m.group(2))
            return {
                "reference_type": "entity_from_row",
                "row_number": row_number,
                "entity_column": entity_column,
                "file_path": m.group(3).strip(),
            }

    # F2B-2: generic ordinal / shorthand extraction (only for single CSV/XLSX paths)
    shorthand = _extract_shorthand_table_reference(text)
    if shorthand:
        return shorthand

    return None


def _parse_ordinal(token: str) -> int | None:
    """Parse an ordinal word or digit form into a 1-based integer."""
    if not token:
        return None
    token = token.strip().lower()
    if token in _ORDINAL_WORDS_LOWER:
        return _ORDINAL_WORDS_LOWER[token]
    m = re.match(r"^(\d+)(st|nd|rd|th)$", token)
    if m:
        return int(m.group(1))
    return None


def _column_index_to_letters(index: int) -> str:
    """Convert a 1-based column index to Excel-style column letters."""
    if index < 1:
        return ""
    letters = ""
    while index > 0:
        index, rem = divmod(index - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


def _extract_single_csv_xlsx_path(text: str) -> str | None:
    """Return the single CSV/XLSX/XLS path in the text, or None if not exactly one."""
    paths = _extract_csv_xlsx_paths(text)
    return paths[0] if len(paths) == 1 else None


def _has_table_reference_intent(text: str) -> bool:
    """Return True if the text contains generic table-reference extraction keywords."""
    return bool(_TABLE_REFERENCE_INTENT_RE.search(text))


def _extract_shorthand_table_reference(text: str) -> dict | None:
    """Extract a generic table reference from ordinal/shorthand phrasing.

    This is not phrase-specific: it parses the table-reference grammar (ordinal,
    row, column, header) and maps it to the existing resolve_table_reference
    reference types. The unique name-like column for 'Nth name' is resolved by
    the tool, not by a hardcoded prompt route.
    """
    file_path = _extract_single_csv_xlsx_path(text)
    if not file_path:
        return None

    # Header ordinal -> cell address in header row
    for pattern in _HEADER_ORDINAL_PATTERNS:
        m = pattern.search(text)
        if m:
            if "card" in m.groupdict() and m.group("card"):
                col_index = int(m.group("card"))
            else:
                col_index = _parse_ordinal(m.group("ord"))
            if col_index and col_index >= 1:
                header_row = 1
                cell_address = f"{_column_index_to_letters(col_index)}{header_row}"
                return {
                    "reference_type": "cell",
                    "cell_address": cell_address,
                    "file_path": file_path,
                }
            return None

    # Row + column shorthand -> entity_from_row
    for pattern in _ROW_COLUMN_SHORTHAND_PATTERNS:
        m = pattern.search(text)
        if m:
            row_number = int(m.group("row"))
            entity_column = m.group("col").strip()
            # Guard against accidental capture of function words.
            if entity_column.lower() in {"in", "of", "the", "column", "row", "for"}:
                continue
            return {
                "reference_type": "entity_from_row",
                "row_number": row_number,
                "entity_column": entity_column,
                "file_path": file_path,
            }

    # Ordinal value in a named column -> entity_from_row at header_row + ordinal
    for pattern in _VALUE_IN_COLUMN_ORDINAL_PATTERNS:
        m = pattern.search(text)
        if m:
            ordinal = _parse_ordinal(m.group("ord"))
            if ordinal and ordinal >= 1:
                header_row = 1
                row_number = header_row + ordinal
                entity_column = m.group("col").strip()
                return {
                    "reference_type": "entity_from_row",
                    "row_number": row_number,
                    "entity_column": entity_column,
                    "file_path": file_path,
                }
            return None

    # Name-like column ordinal -> entity_from_row with auto-discovery sentinel
    for pattern in _NAME_LIKE_ORDINAL_PATTERNS:
        m = pattern.search(text)
        if m:
            ordinal = _parse_ordinal(m.group("ord"))
            if ordinal and ordinal >= 1:
                header_row = 1
                row_number = header_row + ordinal
                return {
                    "reference_type": "entity_from_row",
                    "row_number": row_number,
                    "entity_column": _AUTO_NAME_LIKE_COLUMN,
                    "file_path": file_path,
                }
            return None

    # Ordinal row -> row
    for pattern in _ORDINAL_ROW_PATTERNS:
        m = pattern.search(text)
        if m:
            row_number = _parse_ordinal(m.group("ord"))
            if row_number and row_number >= 1:
                return {
                    "reference_type": "row",
                    "row_number": row_number,
                    "file_path": file_path,
                }
            return None

    return None


def _is_ambiguous_table_reference(user_input: str) -> bool:
    """Return True when the prompt has table-reference intent but no concrete reference.

    This is the compile-time false-success guard: extraction-style prompts that
    cannot be resolved deterministically must not silently downgrade to a
    generic CSV/XLSX read/present workflow.
    """
    if not _has_table_reference_intent(user_input):
        return False
    paths = _extract_csv_xlsx_paths(user_input)
    return len(paths) == 1


_AMBIGUOUS_TABLE_REFERENCE_MESSAGE = (
    "Table reference is ambiguous or incomplete. "
    "Please specify a row number, column/header name, or cell address "
    "(e.g., 'cell B2', 'row 3 Name', or 'third value in Name column')."
)


def _build_ambiguous_table_reference_workflow(user_input: str) -> dict:
    """Build a finalize_output-only workflow that returns a deterministic ambiguous message."""
    step_1 = {
        "id": "step_1",
        "type": "EXECUTE_API",
        "name": "Ambiguous table reference",
        "purpose": "Return deterministic ambiguous/unsupported message for unresolved table reference",
        "expected_outcome": "User sees ambiguous table reference message",
        "risk": "LOW",
        "importance": "LOW",
        "resource_targets": [],
        "agent": "document_local_read",
        "depends_on": [],
        "capability_metadata": {
            "capability_id": "document_local_read",
            "route_confidence": 1.0,
            "route_reason_code": "ambiguous_table_reference",
            "allowed_tool_family": "text_finalization",
            "allowed_tool": "finalize_output",
            "final_action": "ambiguous_table_reference",
            "intent_mode": "ambiguous_table_reference",
            "transform_required": False,
            "static_message": _AMBIGUOUS_TABLE_REFERENCE_MESSAGE,
        },
    }

    return {
        "id": None,
        "name": "document_local_read_workflow",
        "status": "QUEUED",
        "goal": user_input,
        "steps": [step_1],
        "approval_required": False,
    }


def _build_read_file_workflow(user_input: str, file_path: str) -> dict:
    """Build a read_file -> finalize_output candidate workflow."""
    step_1 = {
        "id": "step_1",
        "type": "EXECUTE_API",
        "name": "Read local file",
        "purpose": f"Read the local file \"{file_path}\"",
        "expected_outcome": "File contents retrieved",
        "risk": "LOW",
        "importance": "LOW",
        "resource_targets": [file_path],
        "agent": "document_local_read",  # semantic label only, not execution authority
        "depends_on": [],
        "capability_metadata": {
            "capability_id": "document_local_read",
            "route_confidence": 1.0,
            "route_reason_code": "accepted_explicit_read_file",
            "allowed_tool_family": "file_read",
            "allowed_tool": _resolve_acquisition_tool(file_path, user_input),
        },
        # Do not prepopulate tool_call for file tools (route_prepopulation_allowed=false)
    }

    step_2 = {
        "id": "step_2",
        "type": "EXECUTE_API",
        "name": "Present file contents",
        "purpose": "Present the file contents from step_1",
        "expected_outcome": "Result shown",
        "risk": "LOW",
        "importance": "LOW",
        "resource_targets": [],
        "agent": "document_local_read",
        "depends_on": ["step_1"],
        "capability_metadata": {
            "capability_id": "document_local_read",
            "route_confidence": 1.0,
            "route_reason_code": "accepted_explicit_read_file",
            "allowed_tool_family": "text_finalization",
            "allowed_tool": "finalize_output",
            "final_action": "present",
            "intent_mode": "present",
            "transform_required": False,
        },
    }

    return {
        "id": None,  # set by caller from pre_generated_workflow_id
        "name": "document_local_read_workflow",
        "status": "QUEUED",
        "goal": user_input,
        "steps": [step_1, step_2],
        "approval_required": False,
    }


def _build_transform_file_workflow(
    user_input: str,
    file_path: str,
    final_action: str,
    intent_mode: str,
    purpose_template: str,
    question: str | None = None,
) -> dict:
    """Build a read_file -> finalize_output candidate workflow for a transform final action."""
    route_reason_code = f"accepted_explicit_{final_action}_file"
    step_1 = {
        "id": "step_1",
        "type": "EXECUTE_API",
        "name": "Read local file",
        "purpose": f"Read the local file \"{file_path}\"",
        "expected_outcome": "File contents retrieved",
        "risk": "LOW",
        "importance": "LOW",
        "resource_targets": [file_path],
        "agent": "document_local_read",
        "depends_on": [],
        "capability_metadata": {
            "capability_id": "document_local_read",
            "route_confidence": 1.0,
            "route_reason_code": route_reason_code,
            "allowed_tool_family": "file_read",
            "allowed_tool": _resolve_acquisition_tool(file_path, user_input),
        },
    }

    step_2_meta = {
        "capability_id": "document_local_read",
        "route_confidence": 1.0,
        "route_reason_code": route_reason_code,
        "allowed_tool_family": "text_finalization",
        "allowed_tool": "finalize_output",
        "final_action": final_action,
        "intent_mode": intent_mode,
        "transform_required": True,
    }
    if question is not None:
        step_2_meta["question"] = question

    step_2 = {
        "id": "step_2",
        "type": "EXECUTE_API",
        "name": f"{final_action.replace('_', ' ').title()} file contents",
        "purpose": purpose_template,
        "expected_outcome": "Result shown",
        "risk": "LOW",
        "importance": "LOW",
        "resource_targets": [],
        "agent": "document_local_read",
        "depends_on": ["step_1"],
        "capability_metadata": step_2_meta,
    }

    return {
        "id": None,
        "name": "document_local_read_workflow",
        "status": "QUEUED",
        "goal": user_input,
        "steps": [step_1, step_2],
        "approval_required": False,
    }


def _build_list_files_workflow(user_input: str, folder_path: str) -> dict:
    """Build a list_files -> finalize_output candidate workflow."""
    step_1 = {
        "id": "step_1",
        "type": "EXECUTE_API",
        "name": "List local files",
        "purpose": f"List files in the local folder \"{folder_path}\"",
        "expected_outcome": "File listing retrieved",
        "risk": "LOW",
        "importance": "LOW",
        "resource_targets": [folder_path],
        "agent": "document_local_read",
        "depends_on": [],
        "capability_metadata": {
            "capability_id": "document_local_read",
            "route_confidence": 1.0,
            "route_reason_code": "accepted_explicit_list_files",
            "allowed_tool_family": "file_read",
            "allowed_tool": "list_files",
        },
    }

    step_2 = {
        "id": "step_2",
        "type": "EXECUTE_API",
        "name": "Present file listing",
        "purpose": "Present the file listing from step_1",
        "expected_outcome": "Result shown",
        "risk": "LOW",
        "importance": "LOW",
        "resource_targets": [],
        "agent": "document_local_read",
        "depends_on": ["step_1"],
        "capability_metadata": {
            "capability_id": "document_local_read",
            "route_confidence": 1.0,
            "route_reason_code": "accepted_explicit_list_files",
            "allowed_tool_family": "text_finalization",
            "allowed_tool": "finalize_output",
            "final_action": "present",
            "intent_mode": "list",
            "transform_required": False,
        },
    }

    return {
        "id": None,
        "name": "document_local_read_workflow",
        "status": "QUEUED",
        "goal": user_input,
        "steps": [step_1, step_2],
        "approval_required": False,
    }


def _build_preview_table_schema_workflow(user_input: str, file_path: str) -> dict:
    """Build a preview_table_schema -> finalize_output candidate workflow."""
    file_path = file_path.replace("\\", "/")
    tool_call = f'USE_TOOL: preview_table_schema "{file_path}" "" "1" 1 0 0 0'
    step_1 = {
        "id": "step_1",
        "type": "EXECUTE_API",
        "name": "Preview table schema",
        "purpose": f'Preview the table schema for "{file_path}"',
        "expected_outcome": "Table schema preview retrieved",
        "risk": "LOW",
        "importance": "LOW",
        "resource_targets": [file_path],
        "agent": "document_local_read",
        "depends_on": [],
        "tool_call": tool_call,
        "capability_metadata": {
            "capability_id": "document_local_read",
            "route_confidence": 1.0,
            "route_reason_code": "accepted_preview_table_schema",
            "allowed_tool_family": "file_read",
            "allowed_tool": "preview_table_schema",
        },
    }

    step_2 = {
        "id": "step_2",
        "type": "EXECUTE_API",
        "name": "Present table schema preview",
        "purpose": "Present the table schema preview from step_1",
        "expected_outcome": "Result shown",
        "risk": "LOW",
        "importance": "LOW",
        "resource_targets": [],
        "agent": "document_local_read",
        "depends_on": ["step_1"],
        "capability_metadata": {
            "capability_id": "document_local_read",
            "route_confidence": 1.0,
            "route_reason_code": "accepted_preview_table_schema",
            "allowed_tool_family": "text_finalization",
            "allowed_tool": "finalize_output",
            "final_action": "present",
            "intent_mode": "preview_table_schema",
            "transform_required": False,
        },
    }

    return {
        "id": None,
        "name": "document_local_read_workflow",
        "status": "QUEUED",
        "goal": user_input,
        "steps": [step_1, step_2],
        "approval_required": False,
    }


def _build_resolve_table_reference_workflow(user_input: str, ref: dict) -> dict | None:
    """Build a resolve_table_reference -> finalize_output candidate workflow."""
    reference_type = ref.get("reference_type")
    file_path = (ref.get("file_path") or "").replace("\\", "/")
    if not reference_type or not file_path:
        return None

    if reference_type == "cell":
        cell_address = ref.get("cell_address", "").upper()
        tool_call = f'USE_TOOL: resolve_table_reference "{file_path}" "cell" "" "1" 1 0 "{cell_address}" "" 0 "" 0 0 0'
        purpose = f'Resolve cell {cell_address} in "{file_path}"'
    elif reference_type == "row":
        row_number = ref.get("row_number", 0)
        tool_call = f'USE_TOOL: resolve_table_reference "{file_path}" "row" "" "1" 1 {row_number} "" "" 0 "" 0 0 0'
        purpose = f'Resolve row {row_number} in "{file_path}"'
    elif reference_type == "entity_from_row":
        row_number = ref.get("row_number", 0)
        entity_column = ref.get("entity_column", "")
        tool_call = f'USE_TOOL: resolve_table_reference "{file_path}" "entity_from_row" "" "1" 1 {row_number} "" "" 0 "{entity_column}" 0 0 0'
        purpose = f'Resolve {entity_column} from row {row_number} in "{file_path}"'
    else:
        return None

    step_1 = {
        "id": "step_1",
        "type": "EXECUTE_API",
        "name": "Resolve table reference",
        "purpose": purpose,
        "expected_outcome": "Table reference resolved",
        "risk": "LOW",
        "importance": "LOW",
        "resource_targets": [file_path],
        "agent": "document_local_read",
        "depends_on": [],
        "tool_call": tool_call,
        "capability_metadata": {
            "capability_id": "document_local_read",
            "route_confidence": 1.0,
            "route_reason_code": "accepted_resolve_table_reference",
            "allowed_tool_family": "file_read",
            "allowed_tool": "resolve_table_reference",
        },
    }

    step_2 = {
        "id": "step_2",
        "type": "EXECUTE_API",
        "name": "Present resolved table reference",
        "purpose": "Present the resolved table reference from step_1",
        "expected_outcome": "Result shown",
        "risk": "LOW",
        "importance": "LOW",
        "resource_targets": [],
        "agent": "document_local_read",
        "depends_on": ["step_1"],
        "capability_metadata": {
            "capability_id": "document_local_read",
            "route_confidence": 1.0,
            "route_reason_code": "accepted_resolve_table_reference",
            "allowed_tool_family": "text_finalization",
            "allowed_tool": "finalize_output",
            "final_action": "present",
            "intent_mode": "resolve_table_reference",
            "transform_required": False,
        },
    }

    return {
        "id": None,
        "name": "document_local_read_workflow",
        "status": "QUEUED",
        "goal": user_input,
        "steps": [step_1, step_2],
        "approval_required": False,
    }


def _extract_csv_xlsx_paths(user_input: str) -> list[str]:
    """Return all CSV/XLSX/XLS file paths found in the input (quoted or unquoted)."""
    matches = _CSV_XLSX_PATH_RE.findall(user_input)
    paths = []
    for match in matches:
        # match is a tuple of alternative capture groups; exactly one is non-empty.
        path = next((g for g in match if g), None)
        if path:
            path = path.strip()
            # Reject likely internet domains/files such as "example.com" or "report.html"
            if "." in path and path.rsplit(".", 1)[-1].lower() in {"csv", "xlsx", "xls"}:
                paths.append(path)
    return paths


def _is_bounded_overview_prompt(user_input: str) -> bool:
    """Return True for prompts that route to structured_data_analysis overview."""
    paths = _extract_csv_xlsx_paths(user_input)
    if len(paths) != 1:
        return False
    lower = user_input.lower()
    if any(kw in lower for kw in _SEMANTIC_ANALYSIS_KEYWORDS):
        return False
    return bool(_BOUNDED_OVERVIEW_RE.search(user_input))


def _is_unsupported_spreadsheet_analysis(user_input: str) -> bool:
    """Detect CSV/XLSX numeric/data-analysis prompts beyond the current bounded F5A scope."""
    # Must reference exactly one CSV or XLSX file
    paths = _extract_csv_xlsx_paths(user_input)
    if len(paths) != 1:
        return False
    # Bounded overview prompts are handled by structured_data_analysis, not this guard.
    if _is_bounded_overview_prompt(user_input):
        return False
    # Must contain analysis intent keywords
    return _has_csv_xlsx_analysis_intent(user_input)


def _select_unsupported_spreadsheet_analysis_message(user_input: str) -> str:
    """Choose the unsupported message based on whether the prompt asks for semantic analysis."""
    if any(kw in user_input.lower() for kw in _SEMANTIC_ANALYSIS_KEYWORDS):
        return _SEMANTIC_ANALYSIS_UNSUPPORTED_MESSAGE
    return _UNSUPPORTED_SPREADSHEET_ANALYSIS_MESSAGE


def _build_unsupported_spreadsheet_analysis_workflow(user_input: str) -> dict:
    """Build a finalize_output-only workflow that returns a static unsupported message."""
    static_message = _select_unsupported_spreadsheet_analysis_message(user_input)
    step_1 = {
        "id": "step_1",
        "type": "EXECUTE_API",
        "name": "Unsupported spreadsheet analysis",
        "purpose": "Return deterministic current-scope message for unsupported CSV/XLSX analysis",
        "expected_outcome": "User sees supported operations and remaining open-scope guidance",
        "risk": "LOW",
        "importance": "LOW",
        "resource_targets": [],
        "agent": "document_local_read",
        "depends_on": [],
        "capability_metadata": {
            "capability_id": "document_local_read",
            "route_confidence": 1.0,
            "route_reason_code": "unsupported_spreadsheet_analysis",
            "allowed_tool_family": "text_finalization",
            "allowed_tool": "finalize_output",
            "final_action": "unsupported_spreadsheet_analysis",
            "intent_mode": "unsupported_spreadsheet_analysis",
            "transform_required": False,
            "static_message": static_message,
        },
    }

    return {
        "id": None,
        "name": "document_local_read_workflow",
        "status": "QUEUED",
        "goal": user_input,
        "steps": [step_1],
        "approval_required": False,
    }


def compile_document_local_read_workflow(user_input: str, route_metadata: dict | None = None) -> dict | None:
    """
    Compile a high-confidence explicit read-only local-file prompt into a candidate workflow.

    Returns workflow dict compatible with validate_workflow,
    or None if prompt should fall back to planner.

    Per AGENT_CAPABILITY_ROUTING_CONTRACT_V1 Section 10A:
    - No LLM calls
    - No system_entry import
    - Explicit DAG emission with depends_on
    - Exact literal preservation for file/folder paths
    """
    if not user_input or not isinstance(user_input, str):
        return None

    # === FAIL-SAFE CHECKS ===
    if _is_file_mutation(user_input):
        return None

    # Mixed-domain prompts (e.g. CSV/XLSX + web search) must be checked BEFORE
    # unsupported_spreadsheet_analysis so they fall back to planner instead of
    # being over-captured by the deterministic unsupported guard.
    if _is_mixed_domain(user_input):
        return None

    # === F2B-1: deterministic table schema preview and reference resolution ===
    # Checked before the unsupported spreadsheet analysis guard because prompts
    # like "resolve cell B2" contain "cell"/"row"/"column" keywords that would
    # otherwise be misclassified as future-owned numeric analysis.
    preview_path = _extract_preview_schema_path(user_input)
    if preview_path:
        return _build_preview_table_schema_workflow(user_input, preview_path)

    table_ref = _extract_resolve_table_reference(user_input)
    if table_ref:
        return _build_resolve_table_reference_workflow(user_input, table_ref)

    # Deterministic unsupported CSV/XLSX numeric analysis — only for pure
    # single-domain spreadsheet analysis prompts (no mixed-domain keywords).
    if _is_unsupported_spreadsheet_analysis(user_input):
        return _build_unsupported_spreadsheet_analysis_workflow(user_input)

    # F2B-2 false-success guard: prompts that look like table-reference
    # extraction but could not be resolved to a concrete reference must not
    # silently downgrade to a generic CSV/XLSX read/present workflow.
    if _is_ambiguous_table_reference(user_input):
        return _build_ambiguous_table_reference_workflow(user_input)

    if _is_grep_glob_request(user_input):
        return None
    if _is_ambiguous_file_reference(user_input):
        return None

    # === Supported transform file intents (summarize/explain/extract_key_points) ===
    transform_action = _detect_transform_file_action(user_input)
    if transform_action:
        transform_path = _extract_transform_file_path(user_input, transform_action)
        if transform_path:
            # Guard: unsupported tail intent after transform verb (e.g. "summarize X and tell me...")
            if _has_unsupported_tail_intent(user_input):
                return None
            # Reject extensionless unknown files even for transforms
            if _resolve_acquisition_tool(transform_path, user_input) is None:
                return None
            purpose_templates = {
                "summarize": "Summarize the file contents from step_1",
                "explain": "Explain the file contents from step_1",
                "extract_key_points": "Extract key points from the file contents from step_1",
            }
            return _build_transform_file_workflow(
                user_input,
                transform_path,
                transform_action,
                transform_action,
                purpose_templates[transform_action],
            )
        # Transform verb present but no explicit path → check for tail transform via read path
        tail_transform = _detect_tail_transform(user_input)
        if tail_transform:
            file_path = _extract_read_file_path(user_input)
            if file_path:
                # Reject extensionless unknown files even for tail transforms
                if _resolve_acquisition_tool(file_path, user_input) is None:
                    return None
                purpose_templates = {
                    "summarize": "Summarize the file contents from step_1",
                    "explain": "Explain the file contents from step_1",
                    "extract_key_points": "Extract key points from the file contents from step_1",
                }
                return _build_transform_file_workflow(
                    user_input,
                    file_path,
                    tail_transform,
                    tail_transform,
                    purpose_templates[tail_transform],
                )
        # Transform verb present but no explicit path → fall back to planner
        return None

    # === Unsupported final actions (compare/analyze/fact-check) ===
    if _has_unsupported_final_action(user_input):
        return None

    # === Q&A intents (answer_question) are quarantined per SPRINT-11 REALIGNMENT SLICE A ===
    # They must not route to semantic_transform answer_question.
    # Fall back to planner; accepted summarize/explain/extract_key_points/read paths remain above.

    # === Prevent silent read/present downgrade for question tails ===
    if _has_question_about_file_tail(user_input):
        return None

    # === Try read_file intent ===
    file_path = _extract_read_file_path(user_input)
    if file_path:
        # Guard: supported tail transform (e.g. "read X and summarize it")
        tail_transform = _detect_tail_transform(user_input)
        if tail_transform:
            if _resolve_acquisition_tool(file_path, user_input) is None:
                return None
            purpose_templates = {
                "summarize": "Summarize the file contents from step_1",
                "explain": "Explain the file contents from step_1",
                "extract_key_points": "Extract key points from the file contents from step_1",
            }
            return _build_transform_file_workflow(
                user_input,
                file_path,
                tail_transform,
                tail_transform,
                purpose_templates[tail_transform],
            )

        # Guard: unsupported tail intent (e.g. "read X and tell me...")
        if _has_unsupported_tail_intent(user_input):
            return None

        # CSV/XLSX with analysis intent must not silently downgrade to read/present
        if _is_csv_xlsx(file_path) and _has_csv_xlsx_analysis_intent(user_input):
            return None

        # Reject extensionless unknown files that the resolver cannot identify
        if _resolve_acquisition_tool(file_path, user_input) is None:
            return None
        return _build_read_file_workflow(user_input, file_path)

    # === Try list_files intent ===
    folder_path = _extract_list_files_folder(user_input)
    if folder_path:
        # Guard: unsupported tail intent after list verb
        if _has_unsupported_tail_intent(user_input):
            return None
        return _build_list_files_workflow(user_input, folder_path)

    # === No matching explicit intent ===
    return None
