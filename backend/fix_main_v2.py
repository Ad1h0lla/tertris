"""Fix main.py: add missing variable definitions and fix indentation."""
import os

filepath = os.path.join(os.path.dirname(__file__), "main.py")

with open(filepath, "r", encoding="utf-8") as f:
 content = f.read()

# Fix the broken indentation on line 284
# Replace single-space indent with proper 4-space indent
content = content.replace(
 "\n os.makedirs(workspace_path, exist_ok=True)\n",
 "\n os.makedirs(workspace_path, exist_ok=True)\n"
)

# Add missing variable definitions before db = SessionLocal()
old_db_line = "\n db = SessionLocal()\n try:"

new_block = """
 phase_passed = bool(runner_res.get("passed")) if isinstance(runner_res, dict) else False
 phase_status = "APPROVED" if phase_passed else "REVISION_REQUIRED"
 exec_status = "APPROVED" if phase_passed else "REVISION_REQUIRED"

 db = SessionLocal()
 try:"""

content = content.replace(old_db_line, new_block)

with open(filepath, "w", encoding="utf-8") as f:
 f.write(content)

print("Fix applied successfully!")
print("Changes:")
print("1. Fixed os.makedirs indentation")
print("2. Added phase_passed, phase_status, exec_status definitions")
