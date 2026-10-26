"""Regression checks: real processes/HTTP and Git, with controlled provider output."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
import urllib.error
from unittest.mock import patch

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location('relay_reliability', ROOT/'server.py')
s = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(s)
s = s.application


def init_project(path):
    path.mkdir()
    for args in [('init','-q'), ('config','user.email','test@example.invalid'), ('config','user.name','Relay Test')]:
        subprocess.run(['git','-C',str(path),*args],check=True)
    (path/'edit.txt').write_text('before\n')
    (path/'delete.txt').write_text('delete me\n')
    (path/'.gitignore').write_text('ignored.txt\n')
    s.git(path,'add','.')
    s.git(path,'commit','-qm','Fixture')


class ExportTests(unittest.TestCase):
    def test_export_roundtrip_includes_binary_new_deleted_links_and_modes_without_staging(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);project=base/'project';init_project(project)
            (project/'edit.txt').write_text('staged\n');s.git(project,'add','edit.txt')
            (project/'edit.txt').write_text('final\n')
            before=subprocess.check_output(['git','diff','--cached','--binary'],cwd=project)
            (project/'delete.txt').unlink()
            (project/'new file.txt').write_text('new\n')
            (project/'binary.bin').write_bytes(bytes(range(256)))
            (project/'empty.txt').touch()
            (project/'run.sh').write_text('#!/bin/sh\nexit 0\n');(project/'run.sh').chmod(0o755)
            (project/'link').symlink_to('new file.txt')
            (project/'ignored.txt').write_text('private')
            patch_data=s.complete_patch(project)
            self.assertEqual(subprocess.check_output(['git','diff','--cached','--binary'],cwd=project),before)
            self.assertNotIn(b'ignored.txt',patch_data)
            patch_file=base/'result.patch';patch_file.write_bytes(patch_data)
            target=base/'target';subprocess.run(['git','clone','-q',str(project),str(target)],check=True)
            s.git(target,'apply','--check',str(patch_file));s.git(target,'apply',str(patch_file))
            for name in ['edit.txt','new file.txt','binary.bin','empty.txt','run.sh']:
                self.assertEqual((target/name).read_bytes(),(project/name).read_bytes())
            self.assertFalse((target/'delete.txt').exists())
            self.assertTrue((target/'run.sh').stat().st_mode & 0o111)
            self.assertEqual(os.readlink(target/'link'),'new file.txt')
            self.assertEqual(s.git(project,'ls-files','--others','--exclude-standard'),s.git(target,'ls-files','--others','--exclude-standard'))

    def test_group_permission_error_after_exit_does_not_mask_cancellation(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(s,'DATA',Path(folder)/'data'):
            run=s.Run('fixture',folder)
            process=subprocess.Popen([sys.executable,'-c','pass'],start_new_session=True)
            process.wait()
            run.process=process
            with patch.object(os,'killpg',side_effect=PermissionError('group already exited')):
                run.stop_process();run.stop_process()
            self.assertIsNone(run.process)


class LifecycleTests(unittest.TestCase):
    def wait_for(self, predicate, seconds=15):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            try:
                value=predicate()
                if value:return value
            except (OSError,ValueError,KeyError):pass
            time.sleep(.05)
        self.fail('Lifecycle check timed out')

    def alive(self, pid):
        result=subprocess.run(['ps','-o','stat=','-p',str(pid)],capture_output=True,text=True)
        return bool(result.stdout.strip()) and not result.stdout.strip().startswith('Z')

    def test_stop_and_shutdown_finish_worker_preserve_changes_and_do_not_resume(self):
        for action in ['reject','stop','sigint','sigterm','dev_sigterm']:
            with self.subTest(action=action), tempfile.TemporaryDirectory() as folder:
                base=Path(folder);project=base/'project';init_project(project)
                shutil.copy2(ROOT/'server.py',base/'server.py')
                shutil.copytree(ROOT/'relay',base/'relay')
                shutil.copy2(ROOT/'dev.py',base/'dev.py')
                fake=base/'provider.py'
                fake.write_text('''#!/usr/bin/env python3
import sys,json,os,time,subprocess
from pathlib import Path
if '--version' in sys.argv: print('fixture 1');sys.exit()
if 'auth' in sys.argv or 'login' in sys.argv: print('{"loggedIn":true}');sys.exit()
sys.stdin.read()
if 'workspace-write' in sys.argv:
 Path('partial.txt').write_text('preserve')
 child=subprocess.Popen([sys.executable,'-c',"import signal,time,os;from pathlib import Path;signal.signal(signal.SIGTERM,signal.SIG_IGN);Path('child.pid').write_text(str(os.getpid()));time.sleep(120)"])
 Path('provider.pid').write_text(str(os.getpid()))
 while True:time.sleep(.1)
print(json.dumps({'type':'result','structured_output':{'status':'observed','summary':'Fixture plan','overview':'Fixture','next_actions':[],'findings':[],'acceptance_checks':['fixture']}}),flush=True)
''');fake.chmod(0o755)
                with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
                env=os.environ.copy();env.update(RELAY_CLAUDE=str(fake),RELAY_CODEX=str(fake),PYTHONDONTWRITEBYTECODE='1')
                log=(base/'server.log').open('w')
                def start():return subprocess.Popen([sys.executable,str(base/('dev.py' if action=='dev_sigterm' else 'server.py')),'--port',str(port)],env=env,stdout=log,stderr=log,start_new_session=True)
                token=''
                def request(path,body=None):
                    req=urllib.request.Request(f'http://127.0.0.1:{port}'+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json','X-Relay-Token':token})
                    with urllib.request.urlopen(req,timeout=2) as response:return json.load(response)
                process=start();pids=[]
                try:
                    token=self.wait_for(lambda:request('/api/state'))['token']
                    ident=request('/api/run',{'task':'Fixture','project':str(project),'rounds':1,'minutes':1})['id']
                    def state():return next(r for r in request('/api/state?selected='+ident)['runs'] if r['id']==ident)
                    plan=self.wait_for(lambda:(v if (v:=state())['status']=='awaiting_approval' else None))
                    workspace=Path(plan['workspace'])
                    self.assertFalse(s.git(workspace,'status','--porcelain').strip())
                    if action=='reject':
                        request('/api/stop',{'id':ident})
                        self.wait_for(lambda:state()['status']=='stopped')
                        self.assertFalse((workspace/'provider.pid').exists())
                        continue
                    request('/api/approve-plan',{'id':ident,'plan_id':plan['plan']['id']})
                    for name in ['provider.pid','child.pid']:
                        pids.append(int(self.wait_for(lambda:(workspace/name).read_text())))
                    if action=='stop':
                        request('/api/stop',{'id':ident})
                        self.wait_for(lambda:state()['status']=='stopped')
                        self.wait_for(lambda:all(not self.alive(pid) for pid in pids))
                        self.wait_for(lambda:state().get('export_complete'))
                        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/export?run={ident}') as response:
                            self.assertIn('attachment',response.headers['Content-Disposition'])
                            exported=response.read()
                        self.assertIn(b'partial.txt',exported)
                    else:
                        process.send_signal(signal.SIGINT if action=='sigint' else signal.SIGTERM)
                        process.wait(timeout=15)
                        self.wait_for(lambda:all(not self.alive(pid) for pid in pids))
                        saved=json.loads((base/'data/runs'/ident/'state.json').read_text())
                        self.assertEqual(saved['status'],'stopped')
                        self.assertTrue(saved['export_complete'])
                        process=start();self.wait_for(lambda:request('/api/state'))
                        self.assertEqual(state()['status'],'stopped')
                    self.assertEqual((workspace/'partial.txt').read_text(),'preserve')
                    self.assertTrue((base/'data/baselines'/(ident+'.git')).is_dir())
                finally:
                    for pid in pids:
                        if self.alive(pid):
                            try:os.kill(pid,signal.SIGKILL)
                            except ProcessLookupError:pass
                    if process.poll() is None:
                        process.send_signal(signal.SIGINT)
                        try:process.wait(timeout=15)
                        except subprocess.TimeoutExpired:process.kill();process.wait()
                    log.close()
                self.assertNotIn('Traceback', (base/'server.log').read_text())
