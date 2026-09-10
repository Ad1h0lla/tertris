with open("main.py", "r") as f:
 lines = f.readlines()
lines.insert(281, " workspace_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), \"generated_projects\", execution_id, f\"phase_{phase_num}\")\n")
db_idx = -1
for i in range(320, 340):
 if lines[i].strip() == "db = SessionLocal()":
 db_idx = i
 break
if db_idx >= 0:
 lines.insert(db_idx, "\n")
 lines.insert(db_idx + 1, " phase_passed = bool(runner_res.get(\"passed\")) if isinstance(runner_res, dict) else False\n")
 lines.insert(db_idx + 2, " phase_status = \"APPROVED\" if phase_passed else \"REVISION_REQUIRED\"\n")
 lines.insert(db_idx + 3, " exec_status = \"APPROVED\" if phase_passed else \"REVISION_REQUIRED\"\n")
with open("main.py", "w") as f:
 f.writelines(lines)
print("Done")
