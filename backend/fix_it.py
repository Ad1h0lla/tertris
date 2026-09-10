import os

filepath = os.path.join(os.path.dirname(__file__), "main.py")

with open(filepath, "r", encoding="utf-8") as f:
 lines = f.readlines()

# Add workspace_path before os.makedirs
for i in range(len(lines)):
 if "os.makedirs(workspace_path, exist_ok=True)" in lines[i]:
 lines.insert(i, " workspace_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), \"generated_projects\", execution_id, f\"phase_{phase_num}\")\n")
 print("Inserted workspace_path at line", i + 1)
 break

# Find db = SessionLocal() in _execute_agent_fixed and insert variables
for i in range(len(lines)):
 if lines[i].strip() == "db = SessionLocal()":
 for j in range(max(0, i - 30), i):
 if "_execute_agent_fixed" in lines[j]:
 vars_code = (
 " phase_passed = bool(runner_res.get(\"passed\")) if isinstance(runner_res, dict) else False\n" +
 " phase_status = \"APPROVED\" if phase_passed else \"REVISION_REQUIRED\"\n" +
 " exec_status = \"APPROVED\" if phase_passed else \"REVISION_REQUIRED\"\n\n"
 )
 lines.insert(i, vars_code)
 print("Inserted variables at line", i + 1)
 break
 break

with open(filepath, "w", encoding="utf-8") as f:
 f.writelines(lines)

print("Done!")
