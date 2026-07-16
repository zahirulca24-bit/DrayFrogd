from pathlib import Path

path = Path("app/main.py")
text = path.read_text(encoding="utf-8")
old = '''@app.get("/watchdog/status")
def watchdog_status(_: dict = Depends(require_authenticated)) -> dict:
    return get_watchdog_runtime_status()


@app.get("/watchdog/operations")
def watchdog_operations(_: dict = Depends(require_authenticated)) -> dict:
    global _background_task
    worker_running = _background_task is not None and not _background_task.done()
    return get_watchdog_snapshot(worker_running=worker_running)
'''
new = '''@app.get("/watchdog/status")
def watchdog_status(_: dict = Depends(require_authenticated)) -> dict:
    global _background_task
    worker_running = _background_task is not None and not _background_task.done()
    return get_watchdog_snapshot(worker_running=worker_running)


@app.get("/watchdog/runtime-status")
def watchdog_runtime_status(_: dict = Depends(require_authenticated)) -> dict:
    return get_watchdog_runtime_status()


@app.get("/watchdog/operations")
def watchdog_operations(_: dict = Depends(require_authenticated)) -> dict:
    global _background_task
    worker_running = _background_task is not None and not _background_task.done()
    return get_watchdog_snapshot(worker_running=worker_running)
'''
if old not in text:
    raise RuntimeError("Expected watchdog route block not found")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
