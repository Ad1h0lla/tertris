"""Fix indentation and insert missing variable definitions in main.py."""

FILE = r"E:\tetris.io\idea-engine\backend\main.py"

with open(FILE, "r", encoding="utf-8") as f:
 lines = f.readlines()

# Fix line 282 (index 281): single space -> 4 spaces for os.makedirs
lines[281] = " " + lines[281][1:]

# Fix line 326 (index 325): single space -> 4 spaces for trace = [
lines[325] = " " + lines[325][1:]

# Fix line 327 (index 326): single space -> 8 spaces for agent_selected
lines[326] = " " + lines[326][1:]

# Fix line 328 (index 327): single space -> 8 spaces for agent_completed
lines[327] = " " + lines[327][1:]

# Fix line 329 (index 328): 8 spaces -> 12 spaces for runner_completed
lines[328] = " " + lines[328][8:]

# Fix line 330 (index 329): already correct for reviewer_completed
# (12 spaces starting at column 12, keep as-is)

# Insert workspace_path definition before line 282 (now index 282 after fix)
workspace_path_line = ' workspace_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generated_projects", execution_id, f"phase_{phase_num}")\n'
lines.insert(282, workspace_path_line)

# All subsequent indices shifted by 1
# db = SessionLocal() was at index 324, now at 325
# Insert var_lines before it
var_lines = [
 ' phase_passed = bool(runner_res.get("passed")) if isinstance(runner_res, dict) else False\n',
 ' phase_status = "APPROVED" if phase_passed else "REVISION_REQUIRED"\n',
 ' exec_status = "APPROVED" if phase_passed else "REVISION_REQUIRED"\n',
 '\n',
]

for i, line in enumerate(var_lines):
 lines.insert(326 + i, line)

with open(FILE, "w", encoding="utf-8", newline='\n') as f:
 f.writelines(lines)

print("Done! Applied all fixes.")

# Verify the changes
with open(FILE, "r", encoding="utf-8") as f:
 lines = f.readlines()

print("\nVerification - lines 280-290:")
for i in range(279, 290):
 print(f" {i+1}: {repr(lines[i])}")

print("\nVerification - lines 325-340:")
for i in range(324, 340):
 print(f" {i+1}: {repr(lines[i])}")
