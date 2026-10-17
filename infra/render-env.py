#!/usr/bin/env python3
"""Generate local gcloud JSON env files from a dedicated Firebase Web config."""
import argparse
import os
import json
from pathlib import Path
parser=argparse.ArgumentParser()
parser.add_argument('firebase_config',type=Path)
args=parser.parse_args()
config=json.loads(args.firebase_config.read_text())
project=os.environ.get('GOOGLE_CLOUD_PROJECT','')
if config.get('projectId')!=project or not all(config.get(k) for k in ('apiKey','appId','authDomain')):
    raise SystemExit('A complete Firebase Web config for the approved project is required.')
if config.get('type')=='service_account' or 'private_key' in config:
    raise SystemExit('Do not supply service-account credentials; only public Firebase Web config is accepted.')
common={'GOOGLE_CLOUD_PROJECT':project,'GOOGLE_CLOUD_LOCATION':'global','EVIDENCEDESK_REGION':'asia-south1','EVIDENCEDESK_STORAGE':'cloud','FIRESTORE_DATABASE':'evidencedesk','EVIDENCEDESK_BUCKET':project+'-evidencedesk','EVIDENCEDESK_JOB':'evidencedesk-worker','EVIDENCEDESK_BUDGET_BACKEND':'firestore','EVIDENCEDESK_BUDGET_DOCUMENT':'budgets/development','EVIDENCEDESK_DATA_DIR':'/tmp/evidencedesk'}
web={**common,'EVIDENCEDESK_AUTH':'firebase','FIREBASE_WEB_CONFIG':json.dumps(config,separators=(',',':')),'EVIDENCEDESK_ENABLE_AI':'0'}
worker={**common,'EVIDENCEDESK_ENABLE_AI':'1'}
out=Path(__file__).resolve().parent/'.local'
out.mkdir(exist_ok=True)
for name,values in (('web-env.json',web),('worker-env.json',worker)):
    path=out/name
    path.write_text(json.dumps(values,indent=2)+'\n')
    path.chmod(0o600)
print('Created infra/.local/web-env.json and worker-env.json. Config values were not printed.')
