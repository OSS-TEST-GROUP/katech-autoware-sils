"""Bound console logs without changing ROS log levels or hiding diagnostics."""
import logging.handlers, subprocess, threading

def start_logged(cmd, path):
    handler = logging.handlers.RotatingFileHandler(path, maxBytes=16*1024**2,
                                                  backupCount=4, encoding='utf-8')
    handler.setFormatter(__import__('logging').Formatter('%(message)s'))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    def drain():
        try:
            while True:
                data = proc.stdout.readline(65536)
                if not data: break
                text = data.decode('utf-8', errors='replace').rstrip('\n')
                handler.emit(__import__('logging').LogRecord('console', 20, '', 0, text, (), None))
        finally:
            proc.stdout.close(); handler.close()
    thread = threading.Thread(target=drain, daemon=True)
    thread.start()
    proc.log_thread = thread
    return proc
