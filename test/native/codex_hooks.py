"""Optional no-model native parser probe: python3 test/native/codex_hooks.py.

Only isolated, reviewed synthetic hooks are trusted, through hooks/list +
config/batchWrite. No global trust edit, bypass flag, login or model request.
"""
import json
import os
from pathlib import Path
import queue
import shlex
import shutil
import subprocess
import tempfile
import threading
import time


def probe(text):
    with tempfile.TemporaryDirectory(prefix='fabric-codex-native-') as directory:
        root=Path(directory); home=root/'home';home.mkdir();codex=home/'.codex';codex.mkdir();cwd=root/'project';cwd.mkdir()
        hook=root/'hook.py';hook.write_text('print('+repr(text)+')\n')
        (codex/'config.toml').write_text('model_provider="fixture"\nmodel="fixture"\n[model_providers.fixture]\nname="offline fixture"\nbase_url="http://127.0.0.1:9/v1"\nwire_api="responses"\n[analytics]\nenabled=false\n')
        command='python3 '+shlex.quote(str(hook))
        (codex/'hooks.json').write_text(json.dumps({'hooks':{'SessionStart':[{'hooks':[{'type':'command','command':command,'timeout':5}]}]}}))
        env={k:v for k,v in os.environ.items() if k in ('PATH','TMPDIR','SYSTEMROOT')}
        env.update(HOME=str(home),CODEX_HOME=str(codex),XDG_CONFIG_HOME=str(home/'config'),XDG_DATA_HOME=str(home/'data'),XDG_CACHE_HOME=str(home/'cache'))
        p=subprocess.Popen([shutil.which('codex'),'app-server','--stdio'],cwd=cwd,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)
        q=queue.Queue();events=[];counter=0
        def reader():
            for line in p.stdout:
                try:q.put(json.loads(line))
                except ValueError:pass
        threading.Thread(target=reader,daemon=True).start()
        def request(method,params):
            nonlocal counter
            counter+=1;ident=counter
            p.stdin.write(json.dumps({'id':ident,'method':method,'params':params})+'\n');p.stdin.flush()
            deadline=time.monotonic()+25
            while time.monotonic()<deadline:
                obj=q.get(timeout=max(.01,deadline-time.monotonic()))
                if obj.get('id')==ident:
                    if 'error' in obj:raise RuntimeError(json.dumps(obj['error']))
                    return obj.get('result')
                events.append(obj)
            raise TimeoutError(method)
        try:
            request('initialize',{'clientInfo':{'name':'fabric-native-hook-probe','version':'1'},'capabilities':{'experimentalApi':True}})
            p.stdin.write('{"method":"initialized"}\n');p.stdin.flush()
            listed=request('hooks/list',{'cwds':[str(cwd)]})
            hooks=listed['data'][0]['hooks'];assert len(hooks)==1,listed
            h=hooks[0]
            assert h['command']==command,h
            request('config/batchWrite',{'edits':[{'keyPath':'hooks.state','mergeStrategy':'upsert','value':{h['key']:{'trusted_hash':h['currentHash']}}}],'reloadUserConfig':True})
            listed=request('hooks/list',{'cwds':[str(cwd)]});assert listed['data'][0]['hooks'][0]['trustStatus']=='trusted',listed
            thread=request('thread/start',{'cwd':str(cwd),'ephemeral':True,'approvalPolicy':'never','sandbox':'read-only'})
            request('turn/start',{'threadId':thread['thread']['id'],'input':[{'type':'text','text':'offline hook fixture'}]})
            deadline=time.monotonic()+12
            while time.monotonic()<deadline:
                if any('hook/completed'==e.get('method') for e in events):break
                try:events.append(q.get(timeout=.5))
                except queue.Empty:pass
            completed=[e['params'] for e in events if e.get('method')=='hook/completed']
            assert completed, {'methods':[e.get('method') for e in events]}
            return completed
        finally:
            p.stdin.close()
            try:p.wait(timeout=4)
            except subprocess.TimeoutExpired:p.terminate();p.wait(timeout=4)

if __name__=='__main__':
    before=probe('[fabric-agent-adapter] native fixture')
    after=probe(json.dumps({'hookSpecificOutput':{'hookEventName':'SessionStart','additionalContext':'[fabric-agent-adapter] native fixture'}}))
    before_run=before[0]['run']; after_run=after[0]['run']
    assert before_run['status']=='failed'
    assert before_run['entries']==[{'kind':'error','text':'hook returned invalid session start JSON output'}]
    assert after_run['status']=='completed'
    assert after_run['entries']==[{'kind':'context','text':'[fabric-agent-adapter] native fixture'}]
    print(json.dumps({'host':'codex','baseline_status':before_run['status'],
                      'baseline_error':before_run['entries'][0]['text'],
                      'corrected_status':after_run['status'],'context_received':True,
                      'real_model_calls':0,'provider':'closed loopback fixture'},indent=2))
