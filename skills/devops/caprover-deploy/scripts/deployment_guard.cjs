'use strict';

// Request interlock for the layout-pinned CapRover CLI 2.4.4 deploy command.
// This is not a general Node.js sandbox and must be paired with the Python
// controller's private one-machine registry and minimal environment.
const crypto = require('crypto');
const fs = require('fs');
const http = require('http');
const https = require('https');
const Module = require('module');

const GUARD_VERSION = 1;
const MAX_READS_AFTER_DEPLOY = 256;
const MAX_BODY_BYTES = 1048576;
let policy;
try {
  policy = JSON.parse(Buffer.from(process.env.CAPROVER_DEPLOY_INTERNAL_POLICY || '', 'base64url').toString('utf8'));
} catch (_) {
  process.exit(78);
}
const eventFd = Number(process.env.CAPROVER_DEPLOY_INTERNAL_EVENT_FD);
if (
  !policy || policy.guardVersion !== GUARD_VERSION ||
  typeof policy.origin !== 'string' || typeof policy.appName !== 'string' ||
  typeof policy.sourcePath !== 'string' || !['tarball', 'branch'].includes(policy.sourceMode) ||
  typeof policy.authTokenSha256 !== 'string' || !Number.isInteger(eventFd) || eventFd < 3
) {
  process.exit(78);
}

function emit(event) {
  try {
    fs.writeSync(eventFd, JSON.stringify(event) + '\n');
  } catch (_) {
    process.exit(79);
  }
}

function fail(kind) {
  emit({type: 'violation', kind});
  const error = new Error('CapRover deployment guard blocked the request');
  error.code = 'CAPROVER_DEPLOY_GUARD_BLOCKED';
  throw error;
}

let expectedOrigin;
try {
  expectedOrigin = new URL(policy.origin);
} catch (_) {
  process.exit(78);
}
const encodedApp = encodeURIComponent(policy.appName);
const definitionsPath = '/api/v2/user/apps/appDefinitions';
const deployPath = `/api/v2/user/apps/appData/${encodedApp}?detached=1`;
const buildPath = `/api/v2/user/apps/appData/${encodedApp}`;
let logicalStep = 0;
let transportStep = 0;
let logicalBuildReads = 0;
let transportBuildReads = 0;

function digest(value) {
  return crypto.createHash('sha256').update(value, 'utf8').digest('hex');
}

function headerValue(headers, wanted) {
  if (!headers || typeof headers !== 'object') return undefined;
  const key = Object.keys(headers).find((candidate) => candidate.toLowerCase() === wanted);
  if (!key) return undefined;
  const value = headers[key];
  return Array.isArray(value) ? value.join(',') : value;
}

function validateHeaders(headers) {
  const authToken = headerValue(headers, 'x-captain-auth');
  if (typeof authToken !== 'string' || digest(authToken) !== policy.authTokenSha256) fail('token_header');
  const appToken = headerValue(headers, 'x-captain-app-token');
  if (policy.appTokenSha256) {
    if (typeof appToken !== 'string' || digest(appToken) !== policy.appTokenSha256) fail('token_header');
  } else if (appToken !== undefined) {
    fail('token_header');
  }
  if (headerValue(headers, 'x-namespace') !== 'captain') fail('token_header');
  for (const forbidden of ['authorization', 'proxy-authorization', 'cookie']) {
    if (headerValue(headers, forbidden) !== undefined) fail('token_header');
  }
  const suppliedHost = headerValue(headers, 'host');
  if (suppliedHost !== undefined && String(suppliedHost).toLowerCase() !== expectedOrigin.host.toLowerCase()) {
    fail('host_header');
  }
}

function expected(step, isLogical) {
  if (step < 2) return {method: 'GET', path: definitionsPath};
  if (step === 2) return {method: 'POST', path: deployPath};
  const reads = isLogical ? ++logicalBuildReads : ++transportBuildReads;
  if (reads > MAX_READS_AFTER_DEPLOY) fail('sequence');
  return {method: 'GET', path: buildPath};
}

function validateLogical(method, uri, options) {
  let parsed;
  try {
    parsed = uri instanceof URL ? uri : new URL(String(uri));
  } catch (_) {
    fail('destination');
  }
  if (parsed.origin !== expectedOrigin.origin || parsed.username || parsed.password || parsed.hash) fail('origin');
  const current = expected(logicalStep, true);
  if (String(method).toUpperCase() !== current.method || `${parsed.pathname}${parsed.search}` !== current.path) fail('sequence');
  validateHeaders(options && options.headers);
  if (logicalStep === 2) {
    const form = options && options.formData;
    const stream = form && form.sourceFile;
    const gitHash = form && form.gitHash;
    if (!form || Object.keys(form).sort().join(',') !== 'gitHash,sourceFile' || !stream || stream.path !== policy.sourcePath) {
      fail('deploy_body');
    }
    if (policy.sourceMode === 'tarball' ? gitHash !== '' : !/^[a-f0-9]{40}$/.test(gitHash)) fail('deploy_body');
  } else if (options && (options.formData || options.body)) {
    fail('body');
  }
  logicalStep += 1;
}

function finalOptions(protocol, args) {
  const first = args[0];
  if (typeof first !== 'string' && !(first instanceof URL)) return Object.assign({}, first || {});
  let parsed;
  try {
    parsed = first instanceof URL ? first : new URL(first);
  } catch (_) {
    fail('destination');
  }
  const overrides = args[1] && typeof args[1] === 'object' && !(args[1] instanceof URL) ? args[1] : {};
  return Object.assign({
    protocol: parsed.protocol, hostname: parsed.hostname, port: parsed.port,
    path: `${parsed.pathname}${parsed.search}`,
    sourceUserinfo: Boolean(parsed.username || parsed.password), hash: parsed.hash,
  }, overrides);
}

function validateTransport(transport, protocol, args) {
  const options = finalOptions(protocol, args);
  if (
    options.socketPath || options.createConnection || options.lookup || options.proxy ||
    options.auth !== undefined || options.username !== undefined || options.password !== undefined ||
    options.sourceUserinfo || options.hash
  ) fail('transport');
  if (options.agent !== undefined && options.agent !== false) {
    const prototype = transport === http ? http.Agent.prototype : https.Agent.prototype;
    if (Object.getPrototypeOf(options.agent) !== prototype || Object.hasOwn(options.agent, 'createConnection')) fail('agent');
  }
  const scheme = String(options.protocol || protocol);
  let hostname = String(options.hostname || options.host || '').toLowerCase();
  if (hostname.startsWith('[') && hostname.endsWith(']')) hostname = hostname.slice(1, -1);
  let expectedHost = expectedOrigin.hostname.toLowerCase();
  if (expectedHost.startsWith('[') && expectedHost.endsWith(']')) expectedHost = expectedHost.slice(1, -1);
  const port = String(options.port || (scheme === 'https:' ? 443 : 80));
  const expectedPort = String(expectedOrigin.port || (expectedOrigin.protocol === 'https:' ? 443 : 80));
  if (scheme !== protocol || scheme !== expectedOrigin.protocol || hostname !== expectedHost || port !== expectedPort) fail('origin');
  const current = expected(transportStep, false);
  if (String(options.method || 'GET').toUpperCase() !== current.method || String(options.path || '/') !== current.path) fail('sequence');
  validateHeaders(options.headers);
  if (transportStep === 2) emit({type: 'deploy_request', app: policy.appName});
  transportStep += 1;
  return transportStep === 3;
}

function patchTransport(transport, protocol) {
  const original = transport.request;
  transport.request = function guardedRequest(...args) {
    const deployment = validateTransport(transport, protocol, args);
    const req = original.apply(this, args);
    req.prependListener('response', (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400) {
        emit({type: 'violation', kind: 'redirect'});
        res.destroy(new Error('CapRover deployment guard rejected redirect'));
      }
      if (deployment && (res.statusCode < 200 || res.statusCode >= 300)) {
        emit({type: 'deploy_http_failure', httpStatus: Number(res.statusCode) || 0});
      }
      let received = 0;
      res.on('data', (chunk) => {
        received += Buffer.byteLength(chunk);
        if (received > MAX_BODY_BYTES) {
          emit({type: 'violation', kind: 'response_size'});
          res.destroy(new Error('CapRover deployment guard response limit'));
        }
      });
    });
    return req;
  };
  transport.get = function guardedGet(...args) {
    const req = transport.request(...args);
    req.end();
    return req;
  };
}

patchTransport(http, 'http:');
patchTransport(https, 'https:');

const originalLoad = Module._load;
Module._load = function guardedLoad(request, parent, isMain) {
  const exported = originalLoad.apply(this, arguments);
  if (request !== 'request-promise' || exported.__caproverDeployGuarded) return exported;
  for (const methodName of ['get', 'post', 'patch']) {
    if (typeof exported[methodName] !== 'function') continue;
    const original = exported[methodName].bind(exported);
    exported[methodName] = function guardedPromiseRequest(uri, options) {
      validateLogical(methodName.toUpperCase(), uri, options || {});
      const safe = Object.assign({}, options || {}, {
        followRedirect: false, followAllRedirects: false, maxRedirects: 0, strictSSL: true,
      });
      const promise = original(uri, safe);
      if (logicalStep === 3) {
        promise.then(
          (value) => emit({
            type: 'deploy_response',
            captainStatus: Number.isInteger(value && value.status) ? value.status : null,
          }),
          () => emit({type: 'deploy_error'})
        );
      }
      return promise;
    };
  }
  Object.defineProperty(exported, '__caproverDeployGuarded', {value: true});
  return exported;
};

emit({type: 'guard_ready'});
