import os
filepath = os.path.join(os.path.dirname(__file__), "main.py")
with open(filepath, "r", encoding="utf-8") as f:
	lines = f.readlines()
# Insert workspace_path, goal_text, criteria before os.makedirs
for i, line in enumerate(lines):
	if "os.makedirs(workspace_path, exist_ok=True)" in line:
		lines.insert(i, " workspace_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), \"generated_projects\", execution_id, f\"phase_{phase_num}\")\n")
		lines.insert(i+1, " goal_text = goal_dict.get(\"understood_goal\", \"\")\n")
		lines.insert(i+2, " criteria = goal_dict.get(\"acceptance_criteria\", [])\n")
		print("Inserted workspace_path at line", i + 1)
		break
# Insert phase_passed, phase_status, exec_status before db = SessionLocal() in _execute_agent_fixed
for i, line in enumerate(lines):
	if lines[i].strip() == "db = SessionLocal()":
		for j in range(max(0, i - 30), i):
			if "_execute_agent_fixed" in lines[j]:
				vars_code = " phase_passed = bool(runner_res.get(\"passed\")) if isinstance(runner_res, dict) else False\n phase_status = \"APPROVED\" if phase_passed else \"REVISION_REQUIRED\"\n exec_status = \"APPROVED\" if phase_passed else \"REVISION_REQUIRED\"\n\n"
				lines.insert(i, vars_code)
				print("Inserted variables at line", i + 1)
				break
		break
with open(filepath, "w", encoding="utf-8") as f:
	f.writelines(lines)
print("Done!")
