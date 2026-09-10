import re

with open("main.py", "r", encoding="utf-8") as f:
	content = f.read()

# 1. Insert workspace_path before os.makedirs(workspace_path)
content = content.replace(
	"\n os.makedirs(workspace_path, exist_ok=True)\r\n",
	"\n workspace_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), \"generated_projects\", execution_id, f\"phase_{phase_num}\")\n os.makedirs(workspace_path, exist_ok=True)\r\n"
)

# 2. Insert phase_passed, phase_status, exec_status before db = SessionLocal() that's followed by try: trace = [
content = re.sub(
	r"(db = SessionLocal\(\)\r\n try:\r\n trace = \[\r\n)",
	r" phase_passed = bool(runner_res.get(\"passed\")) if isinstance(runner_res, dict) else False\n phase_status = \"APPROVED\" if phase_passed else \"REVISION_REQUIRED\"\n exec_status = \"APPROVED\" if phase_passed else \"REVISION_REQUIRED\"\n\1",
	content
)

with open("main.py", "w", encoding="utf-8", newline="") as f:
	f.write(content)

print("Done!")

# Verify
with open("main.py", "r", encoding="utf-8") as f:
	lines = f.readlines()
for i, line in enumerate(lines):
	if "workspace_path =" in line and "generated_projects" in line:
		print(f"Line {i+1}: {line.rstrip()}")
	if "phase_passed =" in line:
		print(f"Line {i+1}: {line.rstrip()}")
	if "phase_status =" in line:
		print(f"Line {i+1}: {line.rstrip()}")
	if "exec_status =" in line and "REVISION" in line:
		print(f"Line {i+1}: {line.rstrip()}")
