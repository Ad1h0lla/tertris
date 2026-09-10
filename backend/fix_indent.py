"""Fix indentation and add missing variable definitions in main.py"""
import re

with open("main.py", "r", encoding="utf-8") as f:
 content = f.read()

# Fix the indentation on the os.makedirs line
content = content.replace(
 " os.makedirs(workspace_path, exist_ok=True)",
 " os.makedirs(workspace_path, exist_ok=True)"
)

# Add phase_passed, phase_status, exec_status definitions before "db = SessionLocal()"
old = """ runner_res = run_controlled_verification(workspace_path)

 review_res = run_reviewer(
 confirmed_goal=goal_text,
 outcome_type=agent_type,
 acceptance_criteria=criteria,
 built_output=agent_output,
 workspace_path=workspace_path,
 runner_result=runner_res,
 )

 db = SessionLocal()"""

new = """ runner_res = run_controlled_verification(workspace_path)

 review_res = run_reviewer(
 confirmed_goal=goal_text,
 outcome_type=agent_type,
 acceptance_criteria=criteria,
 built_output=agent_output,
 workspace_path=workspace_path,
 runner_result=runner_res,
 )

 phase_passed = bool(runner_res.get("passed")) if isinstance(runner_res, dict) else False
 phase_status = "APPROVED" if phase_passed else "REVISION_REQUIRED"
 exec_status = "APPROVED" if phase_passed else "REVISION_REQUIRED"

 db = SessionLocal()"""

content = content.replace(old, new)

with open("main.py", "w", encoding="utf-8") as f:
 f.write(content)

print("Done!")
