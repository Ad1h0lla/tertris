"""Fix indentation and insert missing variable definitions in main.py."""
import re

FILE = r"E:\tetris.io\idea-engine\backend\main.py"

with open(FILE, "r", encoding="utf-8") as f:
 content = f.read()

# 1. Fix os.makedirs indentation (currently 1 space, needs 4)
content = content.replace(
 "\n os.makedirs(workspace_path, exist_ok=True)\n",
 "\n os.makedirs(workspace_path, exist_ok=True)\n"
)

# 2. Fix trace = [ indentation (currently 1 space, needs 4)
content = content.replace(
 "\n trace = [\n",
 "\n trace = [\n"
)

# 3. Fix {"step": "agent_selected" indentation (currently 1 space, needs 8)
content = content.replace(
 '\n {"step": "agent_selected"',
 '\n {"step": "agent_selected"'
)

# 4. Fix {"step": "agent_completed" indentation (currently 1 space, needs 8)
content = content.replace(
 '\n {"step": "agent_completed"',
 '\n {"step": "agent_completed"'
)

# 5. Fix {"step": "runner_completed" indentation (needs 8 spaces)
content = content.replace(
 ' {"step": "runner_completed"',
 ' {"step": "runner_completed"'
)

# 6. Fix {"step": "reviewer_completed" indentation (needs 8 spaces)
content = content.replace(
 ' {"step": "reviewer_completed"',
 ' {"step": "reviewer_completed"'
)

# Now insert workspace_path definition before os.makedirs
workspace_path_def = ' workspace_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generated_projects", execution_id, f"phase_{phase_num}")\n'

content = content.replace(
 " os.makedirs(workspace_path, exist_ok=True)\n",
 workspace_path_def + " os.makedirs(workspace_path, exist_ok=True)\n"
)

# Insert phase_passed, phase_status, exec_status before db = SessionLocal() at line 324
var_defs = """ phase_passed = bool(runner_res.get("passed")) if isinstance(runner_res, dict) else False
 phase_status = "APPROVED" if phase_passed else "REVISION_REQUIRED"
 exec_status = "APPROVED" if phase_passed else "REVISION_REQUIRED"

"""

content = content.replace(
 " db = SessionLocal()\n try:\n trace",
 " db = SessionLocal()\n try:\n" + var_defs + " trace"
)

with open(FILE, "w", encoding="utf-8") as f:
 f.write(content)

print("Done! Applied all fixes.")
