"""Standalone entry point, with an optional packaged integration check."""
import os
import sys


if __name__ == '__main__':
    from PyQt6.QtWidgets import QApplication
    # Keep the Qt application alive until os._exit. A local reference inside
    # run()/run_check() can destroy it on return, triggering GPU teardown first.
    application = QApplication.instance() or QApplication(sys.argv)
    if len(sys.argv) == 3 and sys.argv[1] == '--self-test':
        from standalone_check import run_check
        code = run_check(sys.argv[2])
    else:
        from main import run
        code = run()
    # Avoid Qt/OpenGL teardown ordering crashes, as in main.py.
    for stream in (sys.stdout, sys.stderr):
        if stream is not None:
            stream.flush()
    os._exit(code)
