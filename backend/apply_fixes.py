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

print(f"Found os.makedirs at line {ws_idx + 1}")
print(f"Found db=SessionLocal at line {db_idx + 1}")

ws_def = ' workspace_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generated_projects", execution_id, f"phase_{phase_num}")\n'
lines.insert(ws_idx, ws_def)
db_idx += 1
lines.insert(db_idx, ' phase_passed = bool(runner_res.get("passed")) if isinstance(runner_res, dict) else False\n')
lines.insert(db_idx + 1, ' phase_status = "APPROVED" if phase_passed else "REVISION_REQUIRED"\n')
lines.insert(db_idx + 2, ' exec_status = "APPROVED" if phase_passed else "REVISION_REQUIRED"\n')

with open('main.py', 'w', encoding='utf-8', newline='\n') as f:
	f.writelines(lines)

print("Done! Verifying...")
with open('main.py', 'r', encoding='utf-8') as f:
	lines = f.readlines()
for i in [280, 281, 282, 283, 284, 285]:
	print(f"{i+1}: {lines[i].rstrip()}")
print("---")
for i in [325, 326, 327, 328, 329, 330, 331, 332, 333, 334]:
	print(f"{i+1}: {lines[i].rstrip()}")
