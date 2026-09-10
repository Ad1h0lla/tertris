const fs = require("fs");
const path = require("path");

const filepath = path.join(__dirname, "main.py");
let content = fs.readFileSync(filepath, "utf8");

// 1. Add workspace_path + goal_text + criteria before os.makedirs
const beforeMakedirs = [
' workspace_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generated_projects", execution_id, f"phase_{phase_num}")',
' goal_text = goal_dict.get("understood_goal", "")',
' criteria = goal_dict.get("acceptance_criteria", [])',
].join("\n") + "\n";

content = content.replace(
 ' os.makedirs(workspace_path, exist_ok=True)',
 beforeMakedirs + ' os.makedirs(workspace_path, exist_ok=True)'
);

// 2. Add phase_passed, phase_status, exec_status before db = SessionLocal() in _execute_agent_fixed
// Find the right location: after the review_res block, before db = SessionLocal()
const marker = ' db = SessionLocal()\n try:\n trace = [\n {"step": "agent_selected", "type": agent_type, "name": assigned_agent["name"]},';

const varsBlock = [
' phase_passed = bool(runner_res.get("passed")) if isinstance(runner_res, dict) else False',
' phase_status = "APPROVED" if phase_passed else "REVISION_REQUIRED"',
' exec_status = "APPROVED" if phase_passed else "REVISION_REQUIRED"',
'',
].join("\n") + "\n";

content = content.replace(marker, varsBlock + marker);

fs.writeFileSync(filepath, content, "utf8");
console.log("Fixed main.py successfully!");
console.log("- Added workspace_path, goal_text, criteria definitions");
console.log("- Added phase_passed, phase_status, exec_status definitions");
