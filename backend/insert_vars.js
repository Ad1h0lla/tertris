const fs = require("fs");
const filepath = require("path").join(__dirname, "main.py");
let lines = fs.readFileSync(filepath, "utf8").split(/\r?\n/);

// Find line 324 (0-indexed 323) which is empty before "db = SessionLocal()"
// Insert variable definitions there
const insertAt = 324; // 0-indexed: line 325 is "db = SessionLocal()"

const varsBlock = [
 ' phase_passed = bool(runner_res.get("passed")) if isinstance(runner_res, dict) else False',
 ' phase_status = "APPROVED" if phase_passed else "REVISION_REQUIRED"',
 ' exec_status = "APPROVED" if phase_passed else "REVISION_REQUIRED"',
 ''
].join("\n");

lines.splice(insertAt, 0, varsBlock);

fs.writeFileSync(filepath, lines.join("\n"), "utf8");
console.log("Inserted variable definitions at line 325");
console.log("L325:", JSON.stringify(lines[324]));
console.log("L326:", JSON.stringify(lines[325]));
console.log("L327:", JSON.stringify(lines[326]));
console.log("L328:", JSON.stringify(lines[327]));
console.log("Done!");
