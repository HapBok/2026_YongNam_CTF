#!/usr/bin/env python3
"""Process-protocol fixture only. It does not read or transcribe images."""
import json
import os
from pathlib import Path
import sys
import time

args = sys.argv[1:]
sys.stdin.read()
mode = os.environ.get('CTF_METADATA_TEST_MODE', '')
if mode == 'timeout':
    time.sleep(30)
if mode == 'quota':
    print('429 Retry-After: 120', file=sys.stderr)
    sys.exit(1)
if mode == 'tool':
    print(json.dumps({'type': 'item.completed', 'item': {'type': 'command_execution'}}), flush=True)
value = {'title': 'MOCK protocol fixture', 'category': 'crypto',
         'description': 'Process protocol test, not actual OCR.',
         'connections': [], 'source_url': '', 'confidence': .99,
         'needs_review': False, 'warnings': []}
Path(args[args.index('-o')+1]).write_text(json.dumps(value))
print(json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': 0, 'output_tokens': 0}}), flush=True)
