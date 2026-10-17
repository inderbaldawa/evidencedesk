#!/usr/bin/env python3
"""Explicit create-only budget initialization; never resets prior cloud counters."""
import argparse
import os
import json
import sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
parser=argparse.ArgumentParser()
parser.add_argument('ledger_file',type=Path,help='Reviewed JSON containing actual approved limits, approval reference and carried-forward usage')
parser.add_argument('--apply',action='store_true')
args=parser.parse_args()
project=os.environ['GOOGLE_CLOUD_PROJECT']
from app.backend.budget_cloud import _validate
ledger=json.loads(args.ledger_file.read_text())
_validate(ledger)
print(f'Target: {project} / database evidencedesk / document budgets/development')
print(json.dumps({k:ledger[k] for k in ('enabled','approval_reference','model','approved_limits','approved_dispatch_stop_usd','calls','input_tokens','output_tokens','cost_usd')},indent=2))
if not args.apply:
    print('PLAN ONLY. Review aggregate local usage and existing reservations before approval and --apply.');raise SystemExit(0)
from google.cloud import firestore
db=firestore.Client(project=project,database='evidencedesk')
db.document('budgets/development').create(ledger)
print('Created ledger. Existing document would have caused a precondition failure; no reset path exists.')
