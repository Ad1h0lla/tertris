with open("main.py", "r") as f:
 lines = f.readlines()

# Fix 1: Insert workspace_path before os.makedirs (line 282 = index 281)
ws_line = ' workspace_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generated_projects", execution_id, f"phase_{phase_num}")\n'
lines.insert(281, ws_line)

# Fix 2: Insert phase_passed/phase_status/exec_status before db = SessionLocal()
# After fix 1, db = SessionLocal() is at index 325
pp_line = ' phase_passed = bool(runner_res.get("passed")) if isinstance(runner_res, dict) else False\n'
ps_line = ' phase_status = "APPROVED" if phase_passed else "REVISION_REQUIRED"\n'
es_line = ' exec_status = "APPROVED" if phase_passed else "REVISION_REQUIRED"\n'

lines.insert(325, '\n')
lines.insert(326, pp_line)
lines.insert(327, ps_line)
lines.insert(328, es_line)

with open("main.py", "w") as f:
 f.writelines(lines)

print("Done. Verifying...")
with open("main.py", "r") as f:
 lines2 = f.readlines()

for i in range(278, 290):
 print(" %d: %s" % (i+1, lines2[i]), end="")
print()
for i in range(325, 340):
 print(" %d: %s" % (i+1, lines2[i]), end="")
