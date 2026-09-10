const fs = require("fs");
const path = require("path");

const filepath = path.join(__dirname, "main.py");
let content = fs.readFileSync(filepath, "utf8");

// Fix 1: Add workspace_path before os.makedirs (line 283)
content = content.replace(
	"\ os.makedirs(workspace_path, exist_ok=True)",
	" workspace_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), \"generated_projects\", execution_id, f\"phase_{phase_num}\")\n os.makedirs(workspace_path, exist_ok=True)"
);

// Fix 2: Add phase_passed, phase_status, exec_status before db = SessionLocal() in _execute_agent_fixed
// The marker is the empty line + db = SessionLocal() right after review_res block
const marker = "\n db = SessionLocal()\n try:\n trace = [\n {\"step\": \"agent_selected\", \"type\": agent_type, \"name\": assigned_agent[\"name\"]},";

const varsInsert = "\n phase_passed = bool(runner_res.get(\"passed\")) if isinstance(runner_res, dict) else False\n phase_status = \"APPROVED\" if phase_passed else \"REVISION_REQUIRED\"\n exec_status = \"APPROVED\" if phase_passed else \"REVISION_REQUIRED\"\n db = SessionLocal()\n try:\n trace = [\n {\"step\": \"agent_selected\", \"type\": agent_type, \"name\": assigned_agent[\"name\"]},";

content = content.replace(marker, varsInsert);

fs.writeFileSync(filepath, content, "utf8");

// Verify
const lines = content.split("\n");
console.log("Line 282:", JSON.stringify(lines[281]));
console.log("Line 283:", JSON.stringify(lines[282]));
console.log("Line 324:", JSON.stringify(lines[323]));
console.log("Line 325:", JSON.stringify(lines[324]));
console.log("Line 326:", JSON.stringify(lines[325]));
console.log("Line 327:", JSON.stringify(lines[326]));
console.log("Done!");
