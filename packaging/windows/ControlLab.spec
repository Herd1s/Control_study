from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, copy_metadata

root = Path(SPECPATH).resolve().parents[1]
datas = []
for package in ('gymnasium', 'pygame'):
    datas += collect_data_files(package)
datas += collect_data_files('control_lab', include_py_files=True, includes=[
    'lessons/content/*.json', 'lessons/templates/*.py', 'lessons/solutions/*.py',
    'evaluation/assets/*.json',
])
for package in ('control-lab', 'gymnasium', 'numpy', 'pygame'):
    datas += copy_metadata(package)
datas += [
    (str(root / 'src/control_lab/templates/my_controller.py'), 'control_lab/templates'),
    (str(root / 'src/control_lab/controllers/reference_pid.py'), 'control_lab/controllers'),
    (str(root / 'src/control_lab/resources/icon.png'), 'control_lab/resources'),
]
a = Analysis(
    [str(root / 'packaging/windows/entrypoint.py')],
    pathex=[str(root / 'src')],
    binaries=[], datas=datas,
    hiddenimports=['gymnasium.envs.classic_control.cartpole', 'control_lab.templates'],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['tkinter', 'torch', 'isaacsim', 'isaaclab', 'pytest'],
    noarchive=False,
)
pyz = PYZ(a.pure)
gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name='ControlLab',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=False,
          icon=str(root / 'packaging/windows/control_lab.ico'))
cli = EXE(pyz, a.scripts, [], exclude_binaries=True, name='ControlLabCLI',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=True,
          icon=str(root / 'packaging/windows/control_lab.ico'))
coll = COLLECT(gui, cli, a.binaries, a.datas, strip=False, upx=False, name='ControlLab')
