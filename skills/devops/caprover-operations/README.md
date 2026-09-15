# CapRover Operations candidate

This local-only candidate separates saved-session diagnosis from authorized CapRover writes. `probe.py` invokes the official CapRover CLI noninteractively against a protected alias/origin binding. It snapshots only the selected saved machine into a private temporary config store, invokes the mandatory guard, suppresses raw CLI output, and returns fixed, typed metadata.

## Probe interface

Copy `templates/targets.example.json` outside the repository, replace the example, set both that file and the explicitly supplied CapRover registry to owner-only mode, then run:

```bash
chmod 600 /protected/config/targets.json /protected/config/caprover.json
python3 scripts/probe.py \
  --targets /protected/config/targets.json \
  --target example-production \
  --registry /protected/config/caprover.json \
  --cli-root /opt/tools/node_modules/caprover \
  --node /opt/node/bin/node
```

The targets file contains origins, never tokens. The registry is an explicit input; the probe does not search a home directory, credential manager, vault, or environment. Production targets require HTTPS. `--fixture-loopback` permits only explicit HTTP loopback tests.

The probe refuses inherited `CAPROVER_*`, `NODE_OPTIONS`, proxy, and Node TLS override variables. It runs exactly:

```text
caprover api --caproverName <alias> --method GET --path /user/system/info --data '{}' --output true
```

For this command, CapRover CLI 2.4.4 issues exactly three ordered HTTP requests: `GET /api/v2/user/apps/appDefinitions` to check the saved token, `GET /api/v2/user/system/info` from the API command's authentication callback, and a final `GET /api/v2/user/system/info` for the requested action. The guard pins that sequence and blocks a missing, reordered, or fourth request. It also blocks login, renewal, all writes, other endpoints, redirects, and destination changes at request time. Results never reproduce raw response data, paths, origins, tokens, or CLI console text.

## Compatibility and tests

Supported dependency layout: official npm `caprover@2.4.4` only (Apache-2.0, external and not vendored), with pinned hashes for the inspected built entrypoint, API command, HTTP client, API managers, CLI helper, and storage helper. The only tested and accepted Node release is 26.7.0. The pinned validation toolchain for this candidate is Python 3.12.13, pytest 9.1.1, Node 26.7.0, and CapRover CLI 2.4.4; report actual command results rather than assuming compatibility.

Real CLI fixture discovery is explicit:

```bash
CAPROVER_TEST_CLI_ROOT=/opt/tools/node_modules/caprover \
PATH=/opt/node/bin:$PATH \
python3 -m pytest tests -q
```

If `CAPROVER_TEST_CLI_ROOT` is absent, real-CLI fixture tests report skips; that is not a successful fixture validation. The suite uses disposable loopback HTTP with synthetic tokens only. No live/prod validation is claimed.

## Limitations

This diagnoses one narrow session signal. It does not prove broad authorization, server health, application health, or credential freshness beyond the observed sequence. Deployment is a separate operation governed by the companion `caprover-deploy` contract; a probe success never authorizes it. The mandatory monkeypatch guard reduces risk for one inspected dependency layout; it is not OS isolation and does not defend against a malicious local Node binary, CLI package, or same-user process. Protect the inputs and trust the explicitly selected installations.
