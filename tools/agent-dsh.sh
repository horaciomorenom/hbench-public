#!/bin/bash
# Long-tier agent: DeepSeek Harness (dsh, `npm install -g @deepseek-ai/dsh`) in headless mode, in place of pi.
# Use it as a model's agent in models.json: "agent_command": "\"$HB_HOME/tools/agent-dsh.sh\"". long.sh runs it
# in the case's folder with the HB_* variables set. A DeepSeek API URL (api.deepseek.com) goes through dsh's own
# DeepSeek route (its Anthropic-compatible endpoint, same key); any other URL through its OpenAI-compatible route.
# dsh keeps its state in hbench's dsh-agent/ (not ~/.dsh), its session log in logs/session/, and writes its --json
# event stream to logs/agent.jsonl (the transcript view.py and the web UI show). As with pi: no web tools, no skills,
# no sandbox or approvals; and no session-log uploads or telemetry.
set -euo pipefail
export DSH_HOME=$HB_HOME/dsh-agent DSH_PERMISSION_MODE=danger-full-access DSH_TELEMETRY_MODE=DISABLED
mkdir -p "$DSH_HOME"
patch=$HB_LOG_DIR/dsh-patch.json
python3 - "$patch" <<'EOF'
import json, os, sys
e = os.environ
url, mid, effort = e["HB_BASE_URL"], e["HB_MODEL_ID"], e.get("HB_EFFORT") or "high"
off = lambda *ids: [dict(id=i, disabled=True) for i in ids]
rows = off("web", "web-search-deepseek", "web-deepseek-api", "web-fetch-http", "tool-web",
           "skill", "skill-filesystem", "tool-skill", "session-title", "session-title-llm")
rows += [dict(id="session-log-deepseek", disabled=True),
         dict(id="approval", config=dict(policy="never")),
         dict(id="session-persistence-jsonl", config=dict(root=f"{e['HB_LOG_DIR']}/session"))]
if "api.deepseek.com" in url:
    rows += [dict(id="agent-default-model", config=dict(provider="deepseek-official", model=mid)),
             dict(id="llm-deepseek", config=dict(apiKeyEnv="HB_API_KEY", reasoningEffort=effort))]
else:
    model = dict(id=mid, contextWindow=int(e.get("HB_CONTEXT") or 32768), maxTokens=int(e.get("HB_MAX_OUTPUT") or 32768))
    rows += [dict(id="agent-default-model", config=dict(provider="hbench", model=mid)),
             dict(id="llm-pi-ai", config=dict(providers=dict(hbench=dict(
                 api="openai-completions", baseURL=url, apiKeyEnv="HB_API_KEY", models=[model]))))]
json.dump(rows, open(sys.argv[1], "w"), indent=1)  # JSON is YAML: dsh reads it as a patch list
EOF
exec dsh --profile headless --patch "$patch" --json < "$HB_PROMPT_FILE" > "$HB_LOG_DIR/agent.jsonl"
