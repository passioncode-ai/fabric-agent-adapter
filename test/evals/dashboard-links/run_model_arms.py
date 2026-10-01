#!/usr/bin/env python3
"""Opt-in bounded model evaluation; uses existing CLI accounts, no tool actions."""
import subprocess,json,tempfile,datetime,sys
from pathlib import Path
repo=Path(__file__).resolve().parents[3]
reference=(repo/'plugins/fabric-agent-adapter/skills/building-fabric-services/references/dashboard-links.md').read_text()
request='''This is a frozen output evaluation, not an operational task. Use no tools, read no files, make no changes. For each case return only a JSON array of objects with id, kind (native_link/browser_link/remote_open/unavailable), url (or null), device_id (or null), status.
Case A: Operator says "Give me the dashboard" on workstation. Viewer=target=workstation. Trusted resolver gives service example-agent.default, open_link fabric-dashboards://service/example-agent.default?path=%2Fdashboard, http_url http://127.0.0.1:47195/dashboard. Host state available. Pick the primary action.
Case B: Operator says "Open the dashboard" on workstation. Installed host open returned open_failed. HTTP origin is reachable. Pick the next action; do not claim a tool actually ran in this evaluation.
Case C: Operator is on phone, target workstation. Same resolver as A. There is NO remote-open transport available. Pick the action you can truthfully deliver now.
'''
records=[]
output=repo/'docs/evidence/evals/dashboard-links/model-arms.json'
output.parent.mkdir(parents=True, exist_ok=True)
if sys.argv[1:] and output.exists():
 records=[r for r in json.loads(output.read_text())['records'] if r['provider'] not in sys.argv[1:]]
with tempfile.TemporaryDirectory(prefix='fabric-output-eval-') as d:
 for provider in (sys.argv[1:] or ['claude','codex']):
  for arm in ['baseline','with_reference']:
   prompt=(('Apply this supplied skill reference:\n'+reference+'\n') if arm=='with_reference' else '')+request
   if provider=='claude':
    cmd=['claude','-p','--safe-mode','--tools','','--strict-mcp-config','--mcp-config','{"mcpServers":{}}','--no-session-persistence','--output-format','json','--max-turns','1','--max-budget-usd','1']
   else:
    cmd=['codex','exec','--ignore-user-config','--ephemeral','--disable','shell_tool','--disable','sleep_tool','--enable','skip_host_skill_discovery','--sandbox','read-only','--skip-git-repo-check','--json','-']
   record={'provider':provider,'arm':arm,'axis':'output correctness with supplied context; automatic routing NOT_RUN'}
   try:
    p=subprocess.run(cmd,input=prompt,text=True,capture_output=True,cwd=d,timeout=75)
    record['exit_code']=p.returncode
    if provider=='claude':
     data=json.loads(p.stdout);record['answer']=data.get('result', '');record['is_error']=data.get('is_error',False)
    else:
     events=[json.loads(x) for x in p.stdout.splitlines() if x.startswith('{')]
     record['answer']='\n'.join(x.get('item',{}).get('text','') for x in events if x.get('type')=='item.completed' and x.get('item',{}).get('type')=='agent_message')
     record['item_types']=[x.get('item',{}).get('type') for x in events if x.get('type')=='item.completed']
     record['tool_items']=sum(x.get('item',{}).get('type') in ['command_execution','mcp_tool_call','web_search','file_change'] for x in events if x.get('type')=='item.completed')
     record['item_errors']=[dict(x['item'], message=x['item'].get('message', '').replace(str(Path.home()), '<home>')) for x in events if x.get('type')=='item.completed' and x.get('item',{}).get('type')=='error']
     record['errors']=[x.get('message',str(x.get('error',''))) for x in events if x.get('type') in ['error','turn.failed']]
   except (subprocess.TimeoutExpired,ValueError) as e:
    record['error_type']=type(e).__name__
   records.append(record)
   print(json.dumps(record),flush=True)
   output.write_text(json.dumps({'observed_at':datetime.datetime.now(datetime.UTC).isoformat(),'scope':'three frozen supplied-context cases; automatic skill activation NOT_RUN','request':request,'records':records},indent=2)+'\n')
