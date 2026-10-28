"""Build the portable single-file Windows application."""
from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent.parent
DIST = WORKSPACE / 'outputs' if ROOT.parent.name == 'work' else ROOT / 'dist'
BUILD = WORKSPACE / 'work' / 'build' if ROOT.parent.name == 'work' else ROOT / 'build'
BUILD.mkdir(parents=True, exist_ok=True)

# Keep the freezer's startup environment clean; exclude unrelated shims and
# ICU DLLs that some runtimes inject into PATH and PyInstaller may bundle.
blocked = ('libheif', 'jxrlib', 'poppler', 'codex-primary-runtime\\dependencies\\bin')
env = dict(os.environ)
env['PATH'] = ';'.join(part for part in env.get('PATH', '').split(';')
                       if not any(token in part.lower() for token in blocked))
env.pop('QT_PLUGIN_PATH', None)
env.pop('QT_QPA_PLATFORM_PLUGIN_PATH', None)

command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
           '--windowed', '--onefile', '--name', 'GuojamView',
           '--icon', str(BUILD / 'GuojamView.ico'),
           '--distpath', str(DIST), '--workpath', str(BUILD / 'pyinstaller'),
           '--specpath', str(BUILD), '--hidden-import', 'pynvml', '--clean']
for module in ['numpy', 'pandas', 'matplotlib', 'scipy', 'PyQt6.QtQml', 'PyQt6.QtQuick',
               'PyQt6.QtWebEngineCore', 'PyQt6.QtWebEngineWidgets', 'PyQt6.QtOpenGL',
               'PyQt6.QtMultimedia']:
    command.extend(['--exclude-module', module])
command.append(str(ROOT / 'app.py'))
subprocess.run(command, check=True, cwd=ROOT, env=env)
print(DIST / 'GuojamView.exe')
