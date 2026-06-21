"""
CATEGORY: METADATA_CONTRACT
AUTHORITY_LAYER: Tool Capability Metadata
VALIDATES:
  - ISSUE-PDIAG-008B11: File tool metadata contract correction
  - write_file explicitly forbids append/add-line/preserve-existing/partial-edit intent
  - append_file use_when/do_not_use_when correctness
  - edit_file do_not_use_when correctness
  - read_file/list_files remain read-only with no mutation overlap
  - AG1 capability view includes use_when/do_not_use_when from tools.json
  - write_file description carries the key prohibition signal
MONKEYPATCH_USAGE: None
TEST_INTENT: METADATA_CONTRACT_VALIDATION
ARCHITECTURAL_SCOPE: tools.json, tool_capability_index.py
"""
import json
import os
import sys
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

MANIFEST_PATH = os.path.join(ROOT, "system", "tool_index", "tools.json")


def load_manifest():
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ══════════════════════════════════════════════════════════════════════════════
# Class 1: write_file metadata contract
# ══════════════════════════════════════════════════════════════════════════════

class TestWriteFileMetadataContract:

    def setup_method(self):
        self.manifest = load_manifest()
        self.wf = self.manifest["write_file"]
        self.do_not = set(self.wf.get("do_not_use_when", []))
        self.use_when = set(self.wf.get("use_when", []))

    # ── B11-WF-1: description must carry append prohibition ────────────────────

    def test_description_contains_append_prohibition(self):
        desc = self.wf.get("description", "")
        assert "append" in desc.lower(), (
            "write_file description must explicitly mention append as forbidden"
        )

    def test_description_contains_do_not_use(self):
        desc = self.wf.get("description", "")
        assert "do not use" in desc.lower() or "do not" in desc.lower(), (
            "write_file description must contain an explicit prohibition signal"
        )

    def test_description_references_append_file(self):
        desc = self.wf.get("description", "")
        assert "append_file" in desc, (
            "write_file description must name append_file as the correct alternative"
        )

    # ── B11-WF-2: use_when must be creation/full-overwrite only ───────────────

    def test_use_when_contains_creating_new_file(self):
        assert any("creating" in e.lower() and "new" in e.lower() for e in self.use_when), (
            "write_file use_when must include creating new file intent"
        )

    def test_use_when_does_not_contain_append_wording(self):
        for entry in self.use_when:
            assert "append" not in entry.lower(), (
                f"write_file use_when must not contain append wording: '{entry}'"
            )
            assert "add a line" not in entry.lower(), (
                f"write_file use_when must not contain add-line wording: '{entry}'"
            )

    # ── B11-WF-3: do_not_use_when must explicitly forbid append ───────────────

    def test_do_not_use_when_forbids_appending(self):
        assert any("appending" in e.lower() for e in self.do_not), (
            "write_file do_not_use_when must explicitly forbid 'appending to an existing file'"
        )

    def test_do_not_use_when_forbids_adding_line(self):
        assert any("adding a line" in e.lower() for e in self.do_not), (
            "write_file do_not_use_when must explicitly forbid 'adding a line to an existing file'"
        )

    def test_do_not_use_when_forbids_continuing_existing_content(self):
        assert any("continuing content" in e.lower() or "already-written" in e.lower() for e in self.do_not), (
            "write_file do_not_use_when must forbid continuing content in an already-written file"
        )

    def test_do_not_use_when_forbids_preserving_existing_content(self):
        assert any("preserving existing" in e.lower() for e in self.do_not), (
            "write_file do_not_use_when must forbid preserving existing file content"
        )

    def test_do_not_use_when_forbids_partial_edit(self):
        assert any("editing or replacing part" in e.lower() or "replacing known text" in e.lower() for e in self.do_not), (
            "write_file do_not_use_when must forbid editing/replacing part of existing file"
        )

    def test_do_not_use_when_references_append_file(self):
        assert any("append_file" in e for e in self.do_not), (
            "write_file do_not_use_when must name append_file as the correct alternative"
        )

    def test_do_not_use_when_references_edit_file(self):
        assert any("edit_file" in e for e in self.do_not), (
            "write_file do_not_use_when must name edit_file as the correct alternative"
        )

    # ── B11-WF-4: do_not_use_when still contains baseline exclusions ──────────

    def test_do_not_use_when_contains_read_only_operations(self):
        assert any("read-only" in e.lower() for e in self.do_not)

    def test_do_not_use_when_contains_web_operations(self):
        assert any("web" in e.lower() for e in self.do_not)

    def test_do_not_use_when_contains_math(self):
        assert any("arithmetic" in e.lower() or "math" in e.lower() for e in self.do_not)

    # ── B11-WF-5: production/category/output_kind unchanged ───────────────────

    def test_production_flag_unchanged(self):
        assert self.wf.get("production") is True

    def test_category_unchanged(self):
        assert self.wf.get("category") == "file_mutation"

    def test_output_kind_unchanged(self):
        assert self.wf.get("output_kind") == "status"

    def test_arg_order_unchanged(self):
        assert self.wf.get("arg_order") == ["path", "content"]

    def test_arg_types_unchanged(self):
        assert self.wf.get("arg_types") == {"path": "string", "content": "string"}


# ══════════════════════════════════════════════════════════════════════════════
# Class 2: append_file metadata contract
# ══════════════════════════════════════════════════════════════════════════════

class TestAppendFileMetadataContract:

    def setup_method(self):
        self.manifest = load_manifest()
        self.af = self.manifest["append_file"]
        self.do_not = set(self.af.get("do_not_use_when", []))
        self.use_when = set(self.af.get("use_when", []))

    def test_use_when_contains_append_existing_file(self):
        assert any("append" in e.lower() and "existing" in e.lower() for e in self.use_when), (
            "append_file use_when must include append to existing file"
        )

    def test_use_when_contains_add_line(self):
        assert any("add a line" in e.lower() for e in self.use_when), (
            "append_file use_when must include add a line"
        )

    def test_use_when_contains_second_line_intent(self):
        assert any("second line" in e.lower() or "already-written" in e.lower() for e in self.use_when), (
            "append_file use_when must include adding a second line to already-written file"
        )

    def test_do_not_use_when_forbids_creating_new_file(self):
        assert any("creating a new file" in e.lower() for e in self.do_not), (
            "append_file do_not_use_when must forbid creating a new file"
        )

    def test_do_not_use_when_forbids_overwriting(self):
        assert any("overwriting" in e.lower() for e in self.do_not), (
            "append_file do_not_use_when must forbid overwriting full file content"
        )

    def test_do_not_use_when_forbids_when_file_not_exist(self):
        assert any("does not exist" in e.lower() for e in self.do_not), (
            "append_file do_not_use_when must forbid use when file does not exist"
        )

    def test_do_not_use_when_references_write_file(self):
        assert any("write_file" in e for e in self.do_not), (
            "append_file do_not_use_when must name write_file as the correct alternative"
        )

    def test_production_flag_unchanged(self):
        assert self.af.get("production") is True

    def test_category_unchanged(self):
        assert self.af.get("category") == "file_mutation"

    def test_output_kind_unchanged(self):
        assert self.af.get("output_kind") == "status"

    def test_arg_order_unchanged(self):
        assert self.af.get("arg_order") == ["path", "content"]


# ══════════════════════════════════════════════════════════════════════════════
# Class 3: edit_file metadata contract
# ══════════════════════════════════════════════════════════════════════════════

class TestEditFileMetadataContract:

    def setup_method(self):
        self.manifest = load_manifest()
        self.ef = self.manifest["edit_file"]
        self.do_not = set(self.ef.get("do_not_use_when", []))
        self.use_when = set(self.ef.get("use_when", []))

    def test_use_when_contains_replacement_intent(self):
        assert any("replacing" in e.lower() or "replacement" in e.lower() for e in self.use_when), (
            "edit_file use_when must include replacing known existing text"
        )

    def test_do_not_use_when_forbids_appending(self):
        assert any("appending" in e.lower() or "add" in e.lower() for e in self.do_not), (
            "edit_file do_not_use_when must forbid appending/adding without old_text"
        )

    def test_do_not_use_when_references_append_file(self):
        assert any("append_file" in e for e in self.do_not), (
            "edit_file do_not_use_when must name append_file as the correct alternative for add-line"
        )

    def test_do_not_use_when_forbids_creating_new_file(self):
        assert any("creating a new file" in e.lower() for e in self.do_not), (
            "edit_file do_not_use_when must forbid creating a new file"
        )

    def test_do_not_use_when_forbids_overwriting(self):
        assert any("overwriting" in e.lower() for e in self.do_not), (
            "edit_file do_not_use_when must forbid overwriting full file"
        )

    def test_do_not_use_when_references_write_file(self):
        assert any("write_file" in e for e in self.do_not), (
            "edit_file do_not_use_when must name write_file as the correct alternative"
        )

    def test_production_flag_unchanged(self):
        assert self.ef.get("production") is True

    def test_category_unchanged(self):
        assert self.ef.get("category") == "file_mutation"

    def test_output_kind_unchanged(self):
        assert self.ef.get("output_kind") == "status"

    def test_arg_order_unchanged(self):
        assert self.ef.get("arg_order") == ["path", "old_text", "new_text", "replace_all", "dry_run"]


# ══════════════════════════════════════════════════════════════════════════════
# Class 4: read_file / list_files — read-only, no mutation overlap
# ══════════════════════════════════════════════════════════════════════════════

class TestReadOnlyToolsMetadataContract:

    def setup_method(self):
        self.manifest = load_manifest()

    def test_read_file_do_not_use_when_contains_writing(self):
        do_not = set(self.manifest["read_file"].get("do_not_use_when", []))
        assert any("writing" in e.lower() or "modifying" in e.lower() for e in do_not), (
            "read_file do_not_use_when must explicitly exclude writing/modifying"
        )

    def test_read_file_category_is_file_local(self):
        assert self.manifest["read_file"].get("category") == "file_local"

    def test_list_files_do_not_use_when_contains_writing(self):
        do_not = set(self.manifest["list_files"].get("do_not_use_when", []))
        assert any("writing" in e.lower() or "modifying" in e.lower() for e in do_not), (
            "list_files do_not_use_when must explicitly exclude writing/modifying"
        )

    def test_list_files_category_is_file_local(self):
        assert self.manifest["list_files"].get("category") == "file_local"

    def test_read_file_production(self):
        assert self.manifest["read_file"].get("production") is True

    def test_list_files_production(self):
        assert self.manifest["list_files"].get("production") is True


# ══════════════════════════════════════════════════════════════════════════════
# Class 5: AG1 capability view propagation
# ══════════════════════════════════════════════════════════════════════════════

class TestAG1CapabilityViewPropagation:

    def setup_method(self):
        from system.tool_index.tool_capability_index import build_ag1_capability_view
        self.view = build_ag1_capability_view()

    def test_write_file_in_ag1_view(self):
        assert "write_file" in self.view

    def test_append_file_in_ag1_view(self):
        assert "append_file" in self.view

    def test_edit_file_in_ag1_view(self):
        assert "edit_file" in self.view

    def test_read_file_in_ag1_view(self):
        assert "read_file" in self.view

    def test_list_files_in_ag1_view(self):
        assert "list_files" in self.view

    def test_write_file_use_when_in_ag1_view(self):
        wf = self.view["write_file"]
        assert isinstance(wf.get("use_when"), list)
        assert len(wf["use_when"]) > 0

    def test_write_file_do_not_use_when_in_ag1_view(self):
        wf = self.view["write_file"]
        assert isinstance(wf.get("do_not_use_when"), list)
        assert any("appending" in e.lower() for e in wf["do_not_use_when"]), (
            "AG1 capability view must include write_file append prohibition"
        )

    def test_write_file_description_in_ag1_view(self):
        desc = self.view["write_file"].get("description", "")
        assert "append" in desc.lower(), (
            "AG1 capability view write_file description must carry append prohibition"
        )
        assert "append_file" in desc, (
            "AG1 capability view write_file description must name append_file"
        )

    def test_append_file_use_when_in_ag1_view(self):
        af = self.view["append_file"]
        assert isinstance(af.get("use_when"), list)
        assert any("append" in e.lower() for e in af["use_when"])

    def test_append_file_do_not_use_when_in_ag1_view(self):
        af = self.view["append_file"]
        assert isinstance(af.get("do_not_use_when"), list)
        assert any("write_file" in e for e in af["do_not_use_when"])

    def test_edit_file_do_not_use_when_in_ag1_view(self):
        ef = self.view["edit_file"]
        assert isinstance(ef.get("do_not_use_when"), list)
        assert any("append_file" in e for e in ef["do_not_use_when"])

    def test_write_file_category_in_ag1_view(self):
        assert self.view["write_file"].get("category") == "file_mutation"

    def test_append_file_category_in_ag1_view(self):
        assert self.view["append_file"].get("category") == "file_mutation"

    # ── Verify no prompt strings were changed — format_ag1_capability_prompt_line
    # renders description (the critical field for AG1). Confirm it includes the
    # updated write_file description.

    def test_ag1_prompt_line_contains_updated_write_file_description(self):
        from system.tool_index.tool_capability_index import format_ag1_capability_prompt_line
        wf_cap = self.view["write_file"]
        rendered = format_ag1_capability_prompt_line(wf_cap)
        assert "append" in rendered.lower(), (
            "AG1 rendered prompt line for write_file must include append prohibition from description"
        )
        assert "append_file" in rendered, (
            "AG1 rendered prompt line for write_file must name append_file"
        )

    def test_ag1_prompt_line_write_file_shows_correct_category(self):
        from system.tool_index.tool_capability_index import format_ag1_capability_prompt_line
        rendered = format_ag1_capability_prompt_line(self.view["write_file"])
        assert "file_mutation" in rendered

    # ── Cross-tool: mutual references are symmetric ────────────────────────────

    def test_write_file_do_not_mentions_append_file_symmetric(self):
        wf_do_not = self.view["write_file"]["do_not_use_when"]
        af_use_when = self.view["append_file"]["use_when"]
        assert any("append_file" in e for e in wf_do_not), "write_file must reference append_file"
        assert any("append" in e.lower() for e in af_use_when), "append_file must signal append intent"

    def test_write_file_do_not_mentions_edit_file_symmetric(self):
        wf_do_not = self.view["write_file"]["do_not_use_when"]
        ef_use_when = self.view["edit_file"]["use_when"]
        assert any("edit_file" in e for e in wf_do_not), "write_file must reference edit_file"
        assert any("replac" in e.lower() for e in ef_use_when), "edit_file must signal replacement intent"
