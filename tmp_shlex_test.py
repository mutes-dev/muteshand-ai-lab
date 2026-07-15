import json, shlex
plan = {
    "version": "TableAnalysisPlanV1",
    "source": {"path": "tmp/sample.csv"},
    "operations": [
        {"operation_id": "op_filter_1", "type": "filter", "column": "Score", "filter_op": "gt", "filter_value": "5"}
    ],
    "requested_operations": ["op_filter_1"],
    "result_operation": "op_filter_1",
    "bounds": {"max_operations": 8, "max_predicates": 6, "max_rows_scanned": 10000, "max_rows_returned": 1000},
}
s = json.dumps(plan, sort_keys=True, separators=(",", ":"))
print("JSON:", s)
escaped = s.replace("\\", "\\\\").replace('"', '\\"')
line = f'USE_TOOL: analyze_table "tmp/sample.csv" "__table_analysis_plan_v1__" "{escaped}" "" "" "" "" ""'
print("LINE:", line)
parts = shlex.split(line)
print("PARTS:", parts)
print("plan arg parsed:", parts[4])
print("json.loads ok:", json.loads(parts[4]) == plan)
