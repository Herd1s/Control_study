"""Include installed third-party licenses alongside the portable build."""
from importlib import metadata
from pathlib import Path
import sys

names = ['gymnasium', 'numpy', 'pygame', 'cloudpickle', 'typing_extensions', 'farama-notifications', 'pyinstaller', 'PySide6', 'PySide6_Essentials', 'PySide6_Addons', 'shiboken6']
parts = ['ControlLab third-party notices\n', 'Python: https://docs.python.org/3/license.html\n']
parts.append(Path(sys.base_prefix, 'LICENSE.txt').read_text(encoding='utf-8', errors='replace') if Path(sys.base_prefix, 'LICENSE.txt').exists() else 'See the Python license link above.')
for name in names:
    dist = metadata.distribution(name)
    parts.append(f'\n\n{name} {dist.version}\n' + '=' * 60)
    # Some wheels ship only a commercial-license notice while recording the
    # available open-source licenses in metadata. Preserve both pieces.
    license_expression = dist.metadata.get('License-Expression') or dist.metadata.get('License')
    if license_expression:
        parts.append('Package license metadata: ' + license_expression)
    for project_url in dist.metadata.get_all('Project-URL') or []:
        parts.append('Project URL: ' + project_url)
    if dist.metadata.get('Home-page'):
        parts.append('Home page: ' + dist.metadata['Home-page'])
    found = False
    for entry in dist.files or []:
        path_parts = [part.lower() for part in entry.parts]
        in_metadata = any(part.endswith('.dist-info') for part in path_parts)
        is_license = (
            entry.name.lower().startswith(('license', 'copying', 'copyright'))
            or 'licenses' in path_parts
        )
        if in_metadata and is_license:
            file = dist.locate_file(entry)
            if file.is_file():
                parts.append('\nInstalled license file: ' + str(entry))
                parts.append(file.read_text(encoding='utf-8', errors='replace'))
                found = True
    if not found:
        parts.append('No license text is included in this installed package metadata.')
for license_file in sorted((Path(__file__).resolve().parents[1] / 'packaging' / 'licenses').glob('*.txt')):
    parts.append('\n' + license_file.name + '\n' + license_file.read_text(encoding='utf-8', errors='replace'))
Path(sys.argv[1]).write_text('\n'.join(parts), encoding='utf-8')
