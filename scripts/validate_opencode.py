"""Validate an OpenCode JSON config against its published schema without logging it."""

import json
import sys

import httpx
from jsonschema import Draft202012Validator

with open(sys.argv[1]) as stream:
    config = json.load(stream)
response = httpx.get("https://opencode.ai/config.json", follow_redirects=True, timeout=30)
response.raise_for_status()
errors = list(Draft202012Validator(response.json()).iter_errors(config))
if errors:
    for error in errors:
        print("Invalid config at:", ".".join(map(str, error.absolute_path)), error.validator)
    raise SystemExit(1)
print("OpenCode configuration validates against the published JSON schema.")
