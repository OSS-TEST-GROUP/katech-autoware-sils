"""Initialize simulator localization and STOP mode; never auto-engage driving."""
import subprocess,time,signal,sys
def stop(*_):sys.exit(0)
signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
for action in ['init','local-stop']:
    for attempt in range(12):
        time.sleep(5)
        p=subprocess.run(['python3','/code/inspect_ros.py',action,'--seconds','5'])
        if p.returncode==0:break
    else:raise RuntimeError('Startup initialization failed: '+action)
print('READY: localization initialized, STOP mode. User must choose a route and engage.',flush=True)
while True:time.sleep(2)
