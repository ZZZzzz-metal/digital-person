"""Resume the authorized B6 WSL setup after Windows restart; all large data on D.

Does not restart Windows, unregister distributions, alter other distros, or submit
to the competition. Uses the original verified bundle and an isolated distro.
"""
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
import winreg

PROJECT = Path(__file__).resolve().parents[1]
SETUP = Path('D:/B2-B6-20261011/setup')
DISTRO = 'B2-B6-Ubuntu22'
DISK = SETUP / 'wsl' / DISTRO
ARCHIVE = SETUP / 'downloads/ubuntu-22.04.5-wsl-amd64.wsl'
ARCHIVE_SHA = '4499c4fe257f2fc83145b429ce211a0a43fd590e70d6261ede616210947d9f8f'
BUNDLE = Path('D:/B2-B6-20261011/candidate-a34f8df')

def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def wsl_path(path):
    path = path.resolve()
    return '/mnt/' + path.drive[0].lower() + '/' + '/'.join(path.parts[1:])

def decode(value):
    return value.decode('utf-16-le' if b'\x00' in value else 'utf-8', errors='replace')

def normalized(path):
    return os.path.normpath(path.removeprefix('\\\\?\\')).casefold()

def registered_base():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Lxss') as key:
            for i in range(winreg.QueryInfoKey(key)[0]):
                with winreg.OpenKey(key, winreg.EnumKey(key, i)) as item:
                    if winreg.QueryValueEx(item, 'DistributionName')[0] == DISTRO:
                        return winreg.QueryValueEx(item, 'BasePath')[0]
    except FileNotFoundError:
        pass
    return None

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', action='store_true', help='Build and run the actual GPU offline candidate after setup')
    args = parser.parse_args()
    if os.name != 'nt':
        raise RuntimeError('This resumption driver is Windows-only')
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
    logs = SETUP / 'logs' / ('resume-' + run_id)
    logs.mkdir(parents=True)
    report = {'started_at_utc': datetime.now(timezone.utc).isoformat(), 'distro': DISTRO,
              'disk_root': str(DISK), 'logs': str(logs), 'setup_complete': False,
              'verification_requested': args.verify, 'gpu_offline_verified': False,
              'windows_restart_performed': False, 'steps': []}

    def run(name, command, timeout=120, linux_timeout_seconds=None):
        started = datetime.now(timezone.utc).isoformat()
        try:
            proc = subprocess.run(command, capture_output=True, timeout=timeout)
            stdout, stderr, exit_code = proc.stdout, proc.stderr, proc.returncode
            client_timed_out = False
        except subprocess.TimeoutExpired as exc:
            stdout, stderr, exit_code = exc.stdout or b'', exc.stderr or b'', None
            client_timed_out = True
        timed_out = client_timed_out or (linux_timeout_seconds is not None and exit_code in (124, 137))
        (logs / (name + '.stdout.txt')).write_text(decode(stdout), encoding='utf-8')
        (logs / (name + '.stderr.txt')).write_text(decode(stderr), encoding='utf-8')
        step = {'name': name, 'command': command, 'started_at_utc': started,
                'finished_at_utc': datetime.now(timezone.utc).isoformat(), 'exit_code': exit_code,
                'timeout_seconds': timeout, 'timed_out': timed_out, 'client_timed_out': client_timed_out,
                'status': 'failed' if timed_out or exit_code else 'succeeded'}
        if linux_timeout_seconds is not None:
            step['linux_timeout_seconds'] = linux_timeout_seconds
        report['steps'].append(step)
        print(json.dumps({'step': name, 'exit_code': exit_code, 'timed_out': timed_out}), flush=True)
        if timed_out:
            raise RuntimeError(name + ' timed out; inspect the D-drive logs')
        if exit_code:
            raise RuntimeError(name + ' failed; inspect the D-drive logs')
        return proc

    try:
        if sha(ARCHIVE) != ARCHIVE_SHA:
            raise RuntimeError('Ubuntu archive no longer matches the verified official digest')
        base = registered_base()
        if base is not None and normalized(base) != normalized(str(DISK.resolve())):
            raise RuntimeError('Distro name is already used at another path; nothing changed')
        if base is None:
            if DISK.exists() and any(DISK.iterdir()):
                raise RuntimeError('Planned distro directory is not empty; nothing overwritten')
            DISK.parent.mkdir(parents=True, exist_ok=True)
            run('import_distro', ['wsl.exe','--import',DISTRO,str(DISK),str(ARCHIVE),'--version','2'], timeout=300)
        if normalized(registered_base() or '') != normalized(str(DISK.resolve())):
            raise RuntimeError('Registered distro disk is not at the expected D path')
        prefix = ['wsl.exe','--distribution',DISTRO,'--user','root','--exec']
        run('actual_linux_boot', prefix + ['uname','-a'])
        # The Linux deadline signals its process group before the Windows client deadline.
        run('linux_setup', prefix + ['timeout','--signal=INT','--kill-after=60s','3600s',
            'bash',wsl_path(PROJECT/'deploy/setup_b6_linux.sh')],
            timeout=3780, linux_timeout_seconds=3600)
        report['setup_complete'] = True
        if args.verify:
            work = '/root/b2-b6/runs/verify-' + run_id
            report['linux_verification_work'] = work
            run('candidate_verification', prefix + ['timeout','--signal=INT','--kill-after=60s','14400s',
                '/opt/b2-b6/env/bin/python',
                wsl_path(PROJECT/'deploy/verify_container.py'),'--bundle',wsl_path(BUNDLE),
                '--test-file',wsl_path(PROJECT/'submission/official-reference/test_inference_data.jsonl'),
                '--work',work], timeout=14580, linux_timeout_seconds=14400)
            proc = run('read_verification', prefix + ['cat',work+'/verification.json'])
            actual = json.loads(decode(proc.stdout))
            report['actual_verification'] = actual
            report['gpu_offline_verified'] = actual.get('gpu_offline_verified') is True
            if not report['gpu_offline_verified']:
                raise RuntimeError('Actual image verification did not pass')
    except Exception as exc:
        report['failure_type'] = type(exc).__name__
        report['failure'] = str(exc) if isinstance(exc, RuntimeError) else 'See D-drive setup logs'
    finally:
        report['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
        target = logs / 'resume-status.json'
        target.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'setup_complete': report['setup_complete'], 'gpu_offline_verified': report['gpu_offline_verified'],
                          'report': str(target), 'failure': report.get('failure')}), flush=True)
    return 0 if report['setup_complete'] and (not args.verify or report['gpu_offline_verified']) else 1

if __name__ == '__main__':
    sys.exit(main())
