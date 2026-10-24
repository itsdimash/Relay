"""Provider subprocess launch, cancellation, process groups, and event decoding."""
import json
import os
import queue
import signal
import subprocess
import threading
import time


class ProcessControl:
    """Run-owned subprocess lifecycle and stream capture; requires the Run interface."""

    def stop_process(self):
        # HTTP Stop, launch cleanup and server shutdown may arrive together.
        # Serialize the entire operation so an old cleanup never signals a new step.
        with self.process_lock:
            process = self.process
            if process is None:
                return
            warnings = []
            def send(sig):
                try:
                    os.killpg(process.pid, sig)
                except ProcessLookupError:
                    pass
                except PermissionError:
                    # macOS can deny group signals after the leader exits. If the
                    # leader is still alive, fall back to signaling it directly.
                    if process.poll() is None:
                        try:
                            process.send_signal(sig)
                        except ProcessLookupError:
                            pass
                        except OSError as error:
                            warnings.append(f'Could not signal agent process: {error}')
                except OSError as error:
                    warnings.append(f'Could not signal agent process group: {error}')
            send(signal.SIGTERM)
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
            # Children can retain pipes even after the leader has exited.
            time.sleep(.2)
            send(signal.SIGKILL)
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                warnings.append('Agent process did not exit after Stop. Inspect it in your system process monitor.')
            if process.poll() is not None:
                self.process = None
            for warning in warnings:
                self.info.setdefault('cleanup_warnings', []).append(warning)
                self.emit('Relay', 'log', warning)

    def launch(self, agent, args, prompt, input_data=None):
        self.check()
        (self.folder / f'{agent.lower()}-{self.info["status"]}-{self.info["round"]}-turn-{len(self.info.get("turns", []))}-observation-{self.info.get("observation_round", 0)}{self.attempt_suffix()}.prompt.txt').write_text(prompt)
        env = os.environ.copy()
        env.pop('CLAUDECODE', None)
        # Child agents are independent sessions, not clients of this app's IPC context.
        for key in ['CODEX_APP_TOOLS_PIPE_PATH', 'CODEX_THREAD_ID', 'CODEX_SESSION_ID',
                    'CODEX_TOOL_CALL_ID', 'CODEX_TASK_WORKSPACE_VERIFYING_IDENTITY',
                    'CODEX_INTERNAL_ORIGINATOR_OVERRIDE']:
            env.pop(key, None)
        with self.process_lock:
            self.check()
            process = subprocess.Popen(args, cwd=self.info['workspace'], env=env,
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       text=True, bufsize=1, start_new_session=True)
            self.process = process
        lines = queue.Queue()
        def pump(stream, source):
            try:
                for line in stream:
                    lines.put((source, line))
            finally:
                stream.close()
                lines.put((source, None))
        for source, stream in [('stdout', process.stdout), ('stderr', process.stderr)]:
            threading.Thread(target=pump, args=(stream, source), daemon=True).start()
        def feed():
            try:
                process.stdin.write(prompt if input_data is None else input_data)
                process.stdin.close()
            except (BrokenPipeError, OSError):
                pass
        threading.Thread(target=feed, daemon=True).start()
        messages, result, ended, errors, provider_failed = [], None, set(), [], False
        try:
            while len(ended) < 2:
                self.check()
                try:
                    source, line = lines.get(timeout=.2)
                except queue.Empty:
                    continue
                if line is None:
                    ended.add(source)
                    continue
                # Keep exact provider events separately from the readable activity feed.
                with (self.folder / 'provider-events.jsonl').open('a') as f:
                    f.write(json.dumps(dict(time=self.app.now(), agent=agent, source=source, line=line.rstrip())) + '\n')
                if source == 'stderr':
                    if line.strip():
                        errors.append(line.strip())
                        self.emit(agent, 'log', line.rstrip()[:4000])
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    self.emit(agent, 'log', line.rstrip()[:4000])
                    continue
                typ = event.get('type', '')
                if agent == 'Codex':
                    item = event.get('item', {})
                    if typ == 'item.completed' and item.get('type') == 'agent_message':
                        message = item.get('text', '')
                        messages.append(message)
                        self.emit(agent, 'message', message)
                    elif typ in ('item.started', 'item.completed') and item.get('type') in ('command_execution', 'file_change'):
                        self.emit(agent, 'tool', item.get('command') or json.dumps(item.get('changes', [])), detail=item.get('aggregated_output', '')[-12000:])
                    elif typ in ('error', 'turn.failed'):
                        provider_failed = True
                        errors.append(str(event.get('message') or event.get('error', event)))
                else:
                    if typ == 'assistant':
                        for block in event.get('message', {}).get('content', []):
                            if block.get('type') == 'text':
                                messages.append(block['text'])
                                self.emit(agent, 'message', block['text'])
                            elif block.get('type') == 'tool_use':
                                self.emit(agent, 'tool', block.get('name', 'Read'), detail=json.dumps(block.get('input', {})))
                    elif typ == 'result':
                        if event.get('is_error'):
                            provider_failed = True
                            errors.append(str(event.get('result') or event.get('errors', 'Claude failed')))
                        result = event.get('structured_output')
                        if event.get('result'):
                            messages.append(event['result'])
            process.wait(timeout=5)
            self.check()
            if process.returncode or provider_failed:
                raise RuntimeError(f'{agent} could not complete this step: ' + '\n'.join(errors[-5:]))
            return result, '\n\n'.join(messages)
        finally:
            self.stop_process()
