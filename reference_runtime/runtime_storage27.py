"""Installation-local storage identity and fail-closed heartbeat guard.

Bulk assets must be on ext4. Runtime is on a different device, with the same
1.5 GiB stop threshold / 10 GiB free-space reserve as the qualified session.
No repair, remount, filesystem fallback, or automatic data deletion.
"""
import json, os, shutil, subprocess, sys, time
from pathlib import Path
SOURCE = Path(__file__).resolve().parent
CONFIG = SOURCE/'runtime_storage27.json'
DIRECTORIES = ('logs','reports','tmp','cache','server_user','signal_network_v1','ndt_integration_v1')
BUDGET = 2*1024**3
HIGH_WATER = BUDGET-512*1024**2
MIN_FREE = 10*1024**3
def config():
    return json.loads(CONFIG.read_text()) if CONFIG.exists() else None
def mount_record(path):
    p = subprocess.run(['findmnt','--json','--target',str(path),'-o','TARGET,SOURCE,FSTYPE,OPTIONS,UUID'],
                       check=True, text=True, capture_output=True, timeout=5)
    return json.loads(p.stdout)['filesystems'][0]
def raid_problem():
    try:
        cfg = config()
        if not cfg: return 'installation_not_initialized'
        current = mount_record(SOURCE.parent)
        for key in ('target','source','fstype','uuid'):
            if current[key] != cfg['bulk_mount'][key]: return 'bulk_mount_identity_changed'
        if 'rw' not in current['options'].split(','): return 'bulk_read_only'
        if current['fstype'] != 'ext4': return 'unsupported_filesystem'
        device = Path(current['source']).resolve().name
        if int(Path('/sys/fs/ext4',device,'errors_count').read_text()) != 0:
            return 'ext4_errors_detected'
        md = Path('/sys/class/block',device,'md/array_state')
        if md.exists() and md.read_text().strip() not in ('active','clean','active-idle','write-pending'):
            return 'raid_not_healthy'
        runtime = Path(cfg['runtime'])
        if runtime.stat().st_dev != cfg['runtime_device']: return 'runtime_device_changed'
        rt_mount = mount_record(runtime)
        for key in ('target','source','fstype','uuid'):
            if rt_mount[key] != cfg['runtime_mount'][key]:return 'runtime_mount_identity_changed'
        if 'rw' not in rt_mount['options'].split(','): return 'runtime_read_only'
        if rt_mount['fstype']=='ext4':
            rt_device=Path(rt_mount['source']).resolve().name
            if int(Path('/sys/fs/ext4',rt_device,'errors_count').read_text())!=0:
                return 'runtime_ext4_errors_detected'
        return None
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        return 'storage_identity_or_health_unavailable'
def usage(path):
    total = 0
    for base, dirs, files in os.walk(path, followlinks=False):
        for name in files:
            p = Path(base)/name
            try:
                if not p.is_symlink(): total += p.stat().st_size
            except FileNotFoundError: pass
    return total
def violation(used, free):
    if used >= HIGH_WATER: return 'runtime_high_water'
    if free < MIN_FREE: return 'internal_disk_low_space'
    return None
def atomic(path, value):
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value,indent=2)+'\n');tmp.replace(path)
def validate(out):
    cfg = config(); assert cfg, 'Run deploy.py init first'
    assert Path(cfg['install_root']) == SOURCE.parent, 'Installation moved: reinitialize a fresh copy'
    assert raid_problem() is None, raid_problem()
    base = Path(cfg['runtime'])
    assert base.is_dir() and not base.is_symlink() and base.stat().st_uid == os.getuid()
    assert base.stat().st_dev != out.stat().st_dev, 'Runtime must be on a separate device'
    for name in DIRECTORIES:
        assert (out/name).is_symlink() and (out/name).resolve() == base/name
    assert violation(usage(base),shutil.disk_usage(base).free) is None
    assert not (base/'guard_fault.json').exists(), 'Review storage fault; do not restart automatically'
    return base
def start_guard(out):
    base=validate(out)
    marker=base/'guard.stop'
    if marker.exists(): marker.unlink()
    log=(base/'guard_console.log').open('a')
    p=subprocess.Popen([sys.executable,str(SOURCE/'runtime_storage27.py'),'watch'],
        stdout=log,stderr=subprocess.STDOUT,start_new_session=True);log.close()
    for _ in range(100):
        if p.poll() is not None: raise RuntimeError('Storage guard failed to start')
        try:
            if json.loads((base/'guard.json').read_text())['pid']==p.pid:return
        except (FileNotFoundError,ValueError):pass
        time.sleep(.05)
    raise RuntimeError('Storage guard heartbeat missing')
def stop_guard():
    cfg=config()
    if cfg:(Path(cfg['runtime'])/'guard.stop').touch()
def guard_health():
    cfg=config()
    if not cfg:return 'installation_not_initialized'
    base=Path(cfg['runtime'])
    try:
        if (base/'guard_fault.json').exists():return 'runtime_storage_fault'
        state=json.loads((base/'guard.json').read_text())
        age=time.time()-state['wall_time']
        if age < -2 or age > 15:return 'runtime_storage_watchdog_stale'
    except (OSError,ValueError,KeyError):return 'runtime_storage_watchdog_unavailable'
    return None
def watch():
    base=Path(config()['runtime'])
    while not (base/'guard.stop').exists():
        used=usage(base);free=shutil.disk_usage(base).free
        record=dict(pid=os.getpid(),wall_time=time.time(),used_bytes=used,free_bytes=free,
                    stop_threshold_bytes=HIGH_WATER,budget_bytes=BUDGET,hard_quota=False)
        reason=violation(used,free) or raid_problem()
        atomic(base/'guard.json',record)
        if reason:
            record['reason']=reason;atomic(base/'guard_fault.json',record)
            try:
                subprocess.run(['docker','exec','ctrack-sils30-control','bash','-lc',
                    'source /opt/autoware/setup.bash && python3 /code/emergency_stop.py'],timeout=15)
            finally:
                subprocess.run([sys.executable,str(SOURCE/'session.py'),'stop'],timeout=180,check=True)
            return
        time.sleep(2)
if __name__=='__main__':
    assert sys.argv[1:]==['watch'];watch()
