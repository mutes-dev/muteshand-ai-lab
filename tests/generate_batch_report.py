# generate_batch_report.py — BATCH REPORTING FOR CHATGPT ANALYSIS

import os
import json
from datetime import datetime

BASE_PATH = "E:/MutesHand"
LOG_DIR = os.path.join(BASE_PATH, "logs", "regression_tests")
REPORT_FILE = os.path.join(LOG_DIR, "batch_report_for_chatgpt.txt")

def read_layer_log(layer_name: str) -> str:
    """Read log file for a specific layer."""
    log_file = os.path.join(LOG_DIR, f"{layer_name.lower()}_layer_regression_log.txt")
    
    if not os.path.exists(log_file):
        return f"[ERROR] Log file not found: {log_file}\n"
    
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"[ERROR] Failed to read {log_file}: {e}\n"

def generate_batch_report():
    """Generate a single consolidated report for ChatGPT analysis."""
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write("="*80 + "\n")
        f.write("AI LAB — BATCH REGRESSION REPORT (FOR CHATGPT ANALYSIS)\n")
        f.write("="*80 + "\n")
        f.write(f"Generated: {timestamp}\n")
        f.write("="*80 + "\n\n")
        
        f.write("INSTRUCTIONS FOR CHATGPT:\n")
        f.write("-" * 80 + "\n")
        f.write("This report contains regression test results for the AI Lab manager system.\n")
        f.write("Tests are organized into three layers:\n")
        f.write("  1. EXECUTION LAYER - Tool execution, chaining, result propagation\n")
        f.write("  2. VALIDATION LAYER - Plan validation, arg checks, schema enforcement\n")
        f.write("  3. PLANNER LAYER - Tool selection, plan structure, decomposition\n")
        f.write("\n")
        f.write("Please analyze:\n")
        f.write("  - Which tests failed and why\n")
        f.write("  - Patterns in failures (if any)\n")
        f.write("  - Whether failures indicate system bugs or test issues\n")
        f.write("  - Recommendations for fixes\n")
        f.write("="*80 + "\n\n")
        
        # Execution Layer
        f.write("\n" + "="*80 + "\n")
        f.write("EXECUTION LAYER RESULTS\n")
        f.write("="*80 + "\n\n")
        f.write(read_layer_log("execution"))
        
        # Validation Layer
        f.write("\n\n" + "="*80 + "\n")
        f.write("VALIDATION LAYER RESULTS\n")
        f.write("="*80 + "\n\n")
        f.write(read_layer_log("validation"))
        
        # Planner Layer
        f.write("\n\n" + "="*80 + "\n")
        f.write("PLANNER LAYER RESULTS\n")
        f.write("="*80 + "\n\n")
        f.write(read_layer_log("planner"))
        
        # Footer
        f.write("\n\n" + "="*80 + "\n")
        f.write("END OF BATCH REPORT\n")
        f.write("="*80 + "\n")
    
    print(f"Batch report generated: {REPORT_FILE}")
    print(f"File size: {os.path.getsize(REPORT_FILE)} bytes")
    print("\nYou can now copy this file and paste it into ChatGPT for analysis.")

if __name__ == "__main__":
    generate_batch_report()
