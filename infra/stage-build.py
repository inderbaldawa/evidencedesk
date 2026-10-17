#!/usr/bin/env python3
"""Make a narrow build context locally; no authentication or network operations."""
from pathlib import Path
import hashlib
import json
import shutil

root = Path(__file__).resolve().parents[1]
target = root / 'infra' / '.stage'
if target.exists():
    raise SystemExit('infra/.stage already exists; inspect and move it aside before creating a fresh build context.')
files = list((root / 'app/backend').glob('*.py'))
files += [root / 'app/requirements.lock']
files += [p for p in (root / 'data/demo-packs').rglob('*') if p.is_file() and p.suffix in {'.pdf','.json'}]
files += [root / 'app/frontend' / name for name in ('package.json', 'package-lock.json', 'index.html', 'tsconfig.json', 'vite.config.ts')]
files += [p for p in (root / 'app/frontend/src').rglob('*') if p.is_file() and p.suffix in {'.ts', '.tsx', '.css', '.svg'}]
files += [root / 'infra' / name for name in ('Dockerfile', 'cloudbuild.yaml')]
manifest=[]
for source in sorted(files):
    if source.is_symlink(): raise SystemExit(f'Symlinks are not permitted: {source.relative_to(root)}')
    relative=source.relative_to(root)
    destination=target / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    manifest.append({'path':str(relative),'bytes':source.stat().st_size,'sha256':hashlib.sha256(source.read_bytes()).hexdigest()})
(target / '.gcloudignore').write_text('.git\n')
(target / 'BUILD_MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(f'Prepared {len(files)} allowlisted files in {target}')
print('Review BUILD_MANIFEST.json before upload. Only the labeled synthetic demo PDFs are included; no credentials, private files, local runtime, video or approval logs are included.')
