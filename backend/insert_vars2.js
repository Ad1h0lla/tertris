const fs = require("fs");
const filepath = require("path").join(__dirname, "main.py");
let content = fs.readFileSync(filepath, "utf8");

// Replace the empty line before "db = SessionLocal()" with our variable definitions
// First, find the exact pattern: empty line, then " db = SessionLocal()"
const marker = "\n db = SessionLocal()";

const replacement =
"\n phase_passed = bool(runner_res.get(\"passed\")) if isinstance(runner_res, dict) else False\n" +
" phase_status = \"APPROVED\" if phase_passed else \"REVISION_REQUIRED\"\n" +
" exec_status = \"APPROVED\" if phase_passed else \"REVISION_REQUIRED\"\n" +
" db = SessionLocal()";

content = content.replace(marker, replacement);
fs.writeFileSync(filepath, content, "utf8");
console.log("Done!");
