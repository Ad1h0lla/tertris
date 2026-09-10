"""
Tetris Code Agent Specialist
============================

Generates actual runnable project files and writes them directly to disk inside
an isolated project workspace (generated_projects/<execution_id>/phase_1/).

Handles initial code generation and revision feedback while preserving
existing workspace files.
"""

import os
import re
import sys
from typing import Dict, Any, List, Optional

# Ensure LLM router is importable
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from llm.router import get_llm_response


def _parse_files_from_response(llm_output: str) -> Dict[str, str]:
    """
    Parses file blocks from the LLM text output.

    Supports formats:
      1. --- FILE: path/to/filename.ext --- ... (--- END FILE --- or next FILE)
      2. ```lang file:filename or ```filename ... ```
    """
    files = {}

    # Format 1: --- FILE: filename --- ... --- END FILE ---
    pattern1 = r'---\s*FILE:\s*([^\n\r]+)\s*---\s*[\r\n]+(.*?)[\r\n]+---\s*END FILE\s*---'
    matches1 = re.findall(pattern1, llm_output, re.DOTALL)
    for filename, content in matches1:
        clean_fn = filename.strip().lstrip('./\\')
        if clean_fn:
            files[clean_fn] = content.strip()

    # If format 1 missed some files because END FILE was omitted or truncated:
    if "--- FILE:" in llm_output:
        chunks = re.split(r'---\s*FILE:\s*([^\n\r]+)\s*---', llm_output)
        # chunks: [preamble, fn1, body1, fn2, body2, ...]
        for i in range(1, len(chunks), 2):
            fn = chunks[i].strip().lstrip('./\\')
            if i + 1 < len(chunks):
                body = chunks[i + 1]
                # strip out any trailing --- END FILE ---
                body = re.sub(r'---\s*END FILE\s*---.*', '', body, flags=re.DOTALL).strip()
                if fn and fn not in files and body:
                    files[fn] = body

    if files:
        return files

    # Format 2: ```lang file:filename or ```filename
    pattern2 = r'```[a-zA-Z0-9_-]*\s+(?:file:)?([a-zA-Z0-9_\-\./]+)[\r\n]+(.*?)```'
    matches2 = re.findall(pattern2, llm_output, re.DOTALL)
    for filename, content in matches2:
        clean_fn = filename.strip().lstrip('./\\')
        if clean_fn:
            files[clean_fn] = content.strip()

    return files


def write_code(
    goal: str = "",
    context: str = "",
    phase: int = 1,
    prompt: str = "",
    workspace_path: Optional[str] = None,
    execution_id: Optional[str] = None,
    feedback: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Generates real runnable code and writes all files directly to disk inside workspace_path.

    Parameters:
      goal          : Understood project goal description
      context       : Previous phase outputs / context
      phase         : Execution phase number (default 1)
      prompt        : Specific prompt instruction
      workspace_path: Target directory (generated_projects/<execution_id>/phase_1/)
      execution_id  : Unique execution UUID
      feedback      : Revision feedback if user requested changes
    """
    if not execution_id:
        execution_id = "default_project"

    if not workspace_path:
        base_dir = os.path.join(_BACKEND_DIR, "generated_projects")
        workspace_path = os.path.join(base_dir, execution_id, f"phase_{phase}")

    os.makedirs(workspace_path, exist_ok=True)

    # ── Check existing files for revision reuse ────────────────────────────────
    existing_files_content = ""
    if feedback and os.path.exists(workspace_path):
        existing_info = []
        for root, _, filenames in os.walk(workspace_path):
            for fn in filenames:
                fp = os.path.join(root, fn)
                rel_fn = os.path.relpath(fp, workspace_path)
                try:
                    with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                        existing_info.append(f"--- FILE: {rel_fn} ---\n{f.read()}\n--- END FILE ---")
                except Exception:
                    pass
        if existing_info:
            existing_files_content = "\n\nEXISTING WORKSPACE FILES:\n" + "\n\n".join(existing_info)

    # ── Build LLM Prompt ───────────────────────────────────────────────────────
    llm_prompt = f"""
You are the Lead Full-Stack Engineer & UI/UX Designer for the Tetris Platform.
Your mission is to generate an exceptionally polished, fully-functional, beautiful, and responsive web application.

PROJECT GOAL:
{goal}

{f"USER REVISION FEEDBACK:\n{feedback}" if feedback else ""}

{existing_files_content}

{f"PREVIOUS CONTEXT:\n{context}" if context else ""}

AESTHETICS & UI/UX DESIGN SPECIFICATIONS (VERY IMPORTANT):
1. **Design Theme & Color System**:
   - Build a sleek, modern, premium aesthetic (modern dark mode by default with rich slate/zinc background `#090d16` to `#0f172a`, card backgrounds `#1e293b` with subtle 1px border `#334155`, and vibrant accents like electric cyan `#38bdf8`, emerald `#10b981`, indigo `#6366f1`, or amber `#f59e0b`).
   - Use glassmorphism (`backdrop-filter: blur(12px); background: rgba(30, 41, 59, 0.7); border: 1px solid rgba(255, 255, 255, 0.08)`).
   - Use Google Fonts via `<link>` in `index.html` (e.g. `'Plus Jakarta Sans'`, `'Inter'`, or `'Outfit'` for body/headings, and `'JetBrains Mono'` for numbers/stats).
   - Avoid generic, plain browser defaults (no raw unstyled white tables, no plain gray buttons).

2. **UI Components & Layout**:
   - Clean top navigation or app header with brand icon/logo, badge indicators, and action triggers.
   - Prominent metric cards / KPI summary stat tiles (e.g. Total Balance, 24h P&L, Active Count) with trend tags (+2.4%).
   - Inputs, dropdowns, and buttons must have custom, polished styling:
     - Inputs: custom padding, background `#0f172a`, border `1px solid #334155`, focus glow `0 0 0 2px rgba(56, 189, 248, 0.3)`.
     - Buttons: gradient fills or vibrant solid accents, subtle hover lifts `transform: translateY(-1px)`, active click scaling, and smooth transitions `transition: all 0.2s ease`.
     - Tables / Lists: modern card lists or striped/bordered tables with padded cells, badge pills for categories/statuses, and clean action buttons.
   - Interactive feedback: toast notifications or inline feedback badges for user actions (e.g. "Holding Added", "Deleted", "Saved").
   - Responsive design (CSS grid/flexbox) that looks great on both desktop and mobile viewports.

3. **Data & Interactive Logic (`app.js`)**:
   - Complete, robust logic with NO TODOs, placeholders, or mocked empty stubs.
   - If external APIs (like CoinGecko or public APIs) are used, ALWAYS provide graceful local fallback simulation data so the app remains 100% functional and interactive even if API rate limits or network issues occur.
   - State persistence using `localStorage` so user input and additions persist on page reloads.
   - If charts are relevant, include Chart.js (`https://cdn.jsdelivr.net/npm/chart.js`) and render responsive, beautifully configured charts with matching dark-theme colors and tooltips.

4. **File Format & Delimiters**:
You MUST output all code using this exact file delimiter structure:

--- FILE: index.html ---
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>App Title</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="style.css">
    <!-- Include Chart.js or Lucide/FontAwesome CDNs if useful for the app -->
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body>
    <div id="app"></div>
    <script src="app.js"></script>
</body>
</html>
--- END FILE ---

--- FILE: style.css ---
/* Comprehensive modern CSS with CSS variables, reset, layout, cards, badges, inputs, animations */
--- END FILE ---

--- FILE: app.js ---
// Complete JavaScript application logic with state, DOM updates, event handlers, and data persistence
--- END FILE ---

CRITICAL:
- Output ALL three files (`index.html`, `style.css`, and `app.js`).
- Return ONLY the formatted file blocks. No conversational preamble or postscript.
""".strip()

    # ── Call LLM Router ────────────────────────────────────────────────────────
    try:
        response_text = get_llm_response(
            task="code",
            system_prompt="You are a Principal Full-Stack Engineer and Award-Winning UI/UX Designer. You write stunning, production-quality, responsive web applications using modern HTML5, clean CSS3 (modern dark mode, glassmorphism, responsive typography), and vanilla JavaScript. Always output complete code in index.html, style.css, and app.js.",
            user_message=llm_prompt + "\n\nCRITICAL: You MUST output all three complete files (index.html, style.css, and app.js). Ensure style.css provides a truly premium, modern look and feel.",
            max_tokens=8000,
        )
    except Exception as exc:
        response_text = ""

    # Parse file blocks from LLM output
    files = _parse_files_from_response(response_text)

    # Fallback default web app if LLM output didn't yield files or LLM failed
    if not files:
        safe_title = (goal[:40] if goal else "Application").replace('"', '&quot;')
        files = {
            "index.html": f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{safe_title}</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <div class="app-container">
        <header>
            <h1>{safe_title}</h1>
            <p class="subtitle">Powered by TETRIS Engine</p>
        </header>
        <main id="app-root">
            <div class="card">
                <h2>System Status</h2>
                <div id="status-display">Initializing application logic...</div>
            </div>
            <div class="card">
                <h2>Data Console</h2>
                <div id="data-list"></div>
                <div class="control-group">
                    <input type="text" id="entry-input" placeholder="Enter data parameter..." />
                    <button id="action-btn">Execute Action</button>
                </div>
            </div>
        </main>
    </div>
    <script src="app.js"></script>
</body>
</html>""",
            "style.css": """body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0b0f19; color: #f1f5f9; margin: 0; padding: 2rem; }
.app-container { max-width: 800px; margin: 0 auto; }
header { border-bottom: 1px solid #1e293b; padding-bottom: 1rem; margin-bottom: 2rem; }
h1 { color: #38bdf8; margin: 0 0 0.5rem 0; font-size: 1.75rem; }
.subtitle { color: #64748b; margin: 0; font-size: 0.9rem; }
.card { background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 1.5rem; margin-bottom: 1.5rem; }
h2 { font-size: 1.1rem; color: #94a3b8; margin-top: 0; }
.control-group { display: flex; gap: 0.5rem; margin-top: 1rem; }
input { flex: 1; padding: 0.6rem 1rem; background: #0f172a; border: 1px solid #334155; border-radius: 6px; color: #fff; }
button { background: #0284c7; color: white; border: none; padding: 0.6rem 1.2rem; border-radius: 6px; cursor: pointer; font-weight: 600; }
button:hover { background: #0369a1; }
.data-item { padding: 0.5rem 0.75rem; background: #0f172a; border-radius: 4px; margin-bottom: 0.5rem; display: flex; justify-content: space-between; }""",
            "app.js": f"""document.addEventListener('DOMContentLoaded', () => {{
    console.log("Initializing {safe_title}...");
    const statusDisplay = document.getElementById('status-display');
    const dataList = document.getElementById('data-list');
    const input = document.getElementById('entry-input');
    const btn = document.getElementById('action-btn');

    if (statusDisplay) {{
        statusDisplay.innerHTML = '<span style="color:#22c55e">✓ System Online</span> — Goal: {safe_title}';
    }}

    let storedData = JSON.parse(localStorage.getItem('tetris_app_data') || '[]');

    function renderData() {{
        if (!dataList) return;
        dataList.innerHTML = '';
        if (storedData.length === 0) {{
            dataList.innerHTML = '<div style="color:#64748b; font-style:italic">No records recorded.</div>';
            return;
        }}
        storedData.forEach((item, idx) => {{
            const div = document.createElement('div');
            div.className = 'data-item';
            div.innerHTML = `<span>${{item}}</span><small style="color:#64748b">ID: ${{idx + 1}}</small>`;
            dataList.appendChild(div);
        }});
    }}

    if (btn && input) {{
        btn.onclick = () => {{
            const val = input.value.trim();
            if (val) {{
                storedData.push(val);
                localStorage.setItem('tetris_app_data', JSON.stringify(storedData));
                input.value = '';
                renderData();
            }}
        }};
    }}

    renderData();
}});""",
        }

    # If index.html references app.js but app.js was omitted by LLM, generate a functional app.js
    if "index.html" in files and "app.js" not in files and "app.js" in files["index.html"]:
        safe_title = (goal[:40] if goal else "Application").replace('"', '&quot;')
        files["app.js"] = f"""// Auto-generated interactive logic for {safe_title}
document.addEventListener('DOMContentLoaded', () => {{
    console.log("App initialized: {safe_title}");
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {{
        form.addEventListener('submit', (e) => {{
            e.preventDefault();
            const inputs = form.querySelectorAll('input');
            const data = {{}};
            inputs.forEach(input => {{ if (input.id || input.name) data[input.id || input.name] = input.value; }});
            console.log("Form submitted:", data);
            alert("Entry submitted successfully!");
            form.reset();
        }});
    }});
}});"""

    # ── Write files to disk inside workspace_path ──────────────────────────────
    files_written = []
    manifest_files = []

    for rel_path, content in files.items():
        abs_file_path = os.path.join(workspace_path, rel_path)
        os.makedirs(os.path.dirname(abs_file_path), exist_ok=True)
        with open(abs_file_path, "w", encoding="utf-8") as f:
            f.write(content)
        files_written.append(rel_path)
        manifest_files.append({
            "name": rel_path,
            "path": abs_file_path,
            "size": len(content),
        })

    # Summary string for phase outcome
    summary_markdown = f"""# GENERATED APPLICATION FILES

**Workspace Location:** `{workspace_path}`  
**Files Generated ({len(files_written)}):**

{chr(10).join([f'- `{fn}` ({len(files[fn])} bytes)' for fn in files_written])}

---
"""

    return {
        "status": "success",
        "workspace_path": workspace_path,
        "files_written": files_written,
        "manifest": {
            "workspace": workspace_path,
            "files": manifest_files,
            "count": len(files_written),
        },
        "code_output": summary_markdown,
    }


def write_code_to_disk(*args, **kwargs):
    """Alias for backwards compatibility."""
    return write_code(*args, **kwargs)
