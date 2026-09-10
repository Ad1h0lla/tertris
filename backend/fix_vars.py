
import re

with open('main.py', 'r', encoding='utf-8') as f:
	lines = f.readlines()

ws_idx = None
db_idx = None
for i, line in enumerate(lines):
	if ws_idx is None and 'os.makedirs(workspace_path, exist_ok=True)' in line:
		ws_idx = i
	if db_idx is None and line.strip() == 'db = SessionLocal()':
		if i + 2 < len(lines) and 'trace = [' in lines[i + 2]:
			db_idx = i

print(f"ws_idx: {ws_idx+1}, db_idx: {db_idx+1}")

ws_def = ' workspace_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generated_projects", execution_id, f"phase_{phase_num}")
'
lines.insert(ws_idx, ws_def)
db_idx += 1
lines.insert(db_idx, ' phase_passed = bool(runner_res.get("passed")) if isinstance(runner_res, dict) else False
')
lines.insert(db_idx + 1, ' phase_status = "APPROVED" if phase_passed else "REVISION_REQUIRED"
')
lines.insert(db_idx + 2, ' exec_status = "APPROVED" if phase_passed else "REVISION_REQUIRED"
')

with open('main.py', 'w', encoding='utf-8', newline='
') as f:
	f.writelines(lines)

print('Done!')
