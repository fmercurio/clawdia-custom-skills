'use strict';

// Mandatory, layout-pinned companion to probe.py. This is a narrow request
// interlock for CapRover CLI 2.4.4, not a general Node.js sandbox.
const crypto = require('crypto');
const fs = require('fs');
const http = require('http');
const https = require('https');
const Module = require('module');

const GUARD_VERSION = 1;
const MAX_BODY_BYTES = 65536;
let policy;
try {
  policy = JSON.parse(Buffer.from(process.env.CAPROVER_PROBE_INTERNAL_POLICY || '', 'base64url').toString('utf8'));
} catch (_) {
  process.exit(78);
}
const eventFd = Number(process.env.CAPROVER_PROBE_INTERNAL_EVENT_FD);
if (
  !policy || policy.guardVersion !== GUARD_VERSION ||
  typeof policy.origin !== 'string' || typeof policy.nonce !== 'string' ||
  typeof policy.authTokenSha256 !== 'string' ||
  !Number.isInteger(eventFd) || eventFd < 3
) {
  process.exit(78);
}

function emit(event) {
  const record = Object.assign({nonce: policy.nonce}, event);
  try {
    fs.writeSync(eventFd, JSON.stringify(record) + '\n');
  } catch (_) {
    process.exit(79);
  }
}

function fail(kind) {
  emit({type: 'violation', kind});
  const error = new Error('CapRover read-only guard blocked the request');
  error.code = 'CAPROVER_GUARD_BLOCKED';
  throw error;
}

let expectedOrigin;
try {
  expectedOrigin = new URL(policy.origin);
} catch (_) {
  process.exit(78);
}

const expectedRequests = [
  {path: '/api/v2/user/apps/appDefinitions', endpoint: 'auth_check'},
  {path: '/api/v2/user/system/info', endpoint: 'captain_info'},
  {path: '/api/v2/user/system/info', endpoint: 'session_probe'},
];
let logicalCount = 0;
let transportCount = 0;

function digest(value) {
  return crypto.createHash('sha256').update(value, 'utf8').digest('hex');
}

const NETWORK_ERROR_CODES = new Set([
  'ECONNREFUSED', 'ECONNRESET', 'ENOTFOUND', 'EAI_AGAIN',
  'ETIMEDOUT', 'EHOSTUNREACH',
]);

function networkErrorCode(error) {
  for (const candidate of [error, error && error.cause, error && error.error]) {
    if (candidate && NETWORK_ERROR_CODES.has(candidate.code)) return candidate.code;
  }
  return 'UNKNOWN';
}

function headerValue(headers, wanted) {
  if (!headers || typeof headers !== 'object') return undefined;
  const key = Object.keys(headers).find((candidate) => candidate.toLowerCase() === wanted);
  if (!key) return undefined;
  const value = headers[key];
  return Array.isArray(value) ? value.join(',') : value;
}

function validateHeaders(options) {
  const headers = options.headers;
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

function isOptions(value) {
  return value !== null && typeof value === 'object' && !(value instanceof URL);
}

function finalOptions(protocol, args) {
  const first = args[0];
  if (typeof first !== 'string' && !(first instanceof URL)) return Object.assign({}, first || {});
  let parsed;
  try {
    parsed = first instanceof URL ? first : new URL(first);
  } catch (_) {
    fail('invalid_destination');
  }
  const fromUrl = {
    protocol: parsed.protocol,
    hostname: parsed.hostname,
    port: parsed.port,
    path: `${parsed.pathname}${parsed.search}`,
    hash: parsed.hash,
    auth: parsed.username || parsed.password
      ? `${decodeURIComponent(parsed.username)}:${decodeURIComponent(parsed.password)}`
      : undefined,
  };
  const overrides = isOptions(args[1]) ? args[1] : {};
  return Object.assign(fromUrl, overrides, {
    protocol: overrides.protocol || parsed.protocol || protocol,
    sourceUserinfo: Boolean(parsed.username || parsed.password),
    sourceQueryOrFragment: Boolean(parsed.search || parsed.hash),
  });
}

function validateNativeAgent(transport, options) {
  if (options.socketPath) fail('socket_path');
  if (typeof options.createConnection === 'function' || typeof options.lookup === 'function') fail('custom_connection');
  if (options.proxy) fail('proxy');
  if (options.agent === undefined || options.agent === false) return;
  const prototype = transport === http ? http.Agent.prototype : https.Agent.prototype;
  if (Object.getPrototypeOf(options.agent) !== prototype || Object.hasOwn(options.agent, 'createConnection')) {
    fail('agent');
  }
}

function destination(protocol, options) {
  const scheme = String(options.protocol || protocol);
  let hostname = options.hostname !== undefined ? options.hostname : options.host;
  hostname = String(hostname || '').toLowerCase();
  if (hostname.startsWith('[') && hostname.endsWith(']')) hostname = hostname.slice(1, -1);
  let port = options.port;
  if (port === undefined || port === null || port === '') port = scheme === 'https:' ? '443' : '80';
  return {scheme, hostname, port: String(port), path: String(options.path || '/')};
}

function validateTransport(transport, protocol, args) {
  const options = finalOptions(protocol, args);
  validateNativeAgent(transport, options);
  if (
    options.sourceUserinfo || options.auth !== undefined ||
    options.username !== undefined || options.password !== undefined
  ) fail('userinfo');
  if (options.sourceQueryOrFragment || options.hash) fail('sequence');
  const target = destination(protocol, options);
  const expectedPort = expectedOrigin.port || (expectedOrigin.protocol === 'https:' ? '443' : '80');
  let expectedHostname = expectedOrigin.hostname.toLowerCase();
  if (expectedHostname.startsWith('[') && expectedHostname.endsWith(']')) {
    expectedHostname = expectedHostname.slice(1, -1);
  }
  if (
    target.scheme !== protocol ||
    target.scheme !== expectedOrigin.protocol ||
    target.hostname !== expectedHostname ||
    target.port !== expectedPort
  ) fail('origin');
  if (String(options.method || 'GET').toUpperCase() !== 'GET') fail('method');
  const next = expectedRequests[transportCount];
  if (!next || target.path !== next.path) fail('sequence');
  validateHeaders(options);
  transportCount += 1;
  emit({type: 'request', endpoint: next.endpoint, sequence: transportCount});
  return {endpoint: next.endpoint, sequence: transportCount};
}

function validateLogical(method, uri) {
  let parsed;
  try {
    parsed = uri instanceof URL ? uri : new URL(String(uri));
  } catch (_) {
    fail('invalid_destination');
  }
  if (String(method).toUpperCase() !== 'GET') fail('method');
  if (parsed.username || parsed.password || parsed.search || parsed.hash || parsed.origin !== expectedOrigin.origin) {
    fail('origin');
  }
  const next = expectedRequests[logicalCount];
  if (!next || parsed.pathname !== next.path) fail('sequence');
  logicalCount += 1;
  return {endpoint: next.endpoint, sequence: logicalCount};
}

function patchTransport(transport, protocol) {
  const original = transport.request;
  transport.request = function guardedRequest(...args) {
    const evidence = validateTransport(transport, protocol, args);
    const req = original.apply(this, args);
    req.prependListener('response', (res) => {
      emit({
        type: 'http_response', endpoint: evidence.endpoint,
        sequence: evidence.sequence, httpStatus: Number(res.statusCode) || 0,
      });
      if (res.statusCode >= 300 && res.statusCode < 400) {
        emit({type: 'violation', kind: 'redirect'});
        res.destroy(new Error('CapRover read-only guard rejected redirect'));
        return;
      }
      let received = 0;
      res.on('data', (chunk) => {
        received += Buffer.byteLength(chunk);
        if (received > MAX_BODY_BYTES) {
          emit({type: 'violation', kind: 'response_size'});
          res.destroy(new Error('CapRover read-only guard response limit'));
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

function schemaFor(endpoint, envelope) {
  if (!envelope || typeof envelope !== 'object' || Array.isArray(envelope)) return 'unknown';
  if (endpoint === 'auth_check') {
    return envelope.data && typeof envelope.data === 'object' && Array.isArray(envelope.data.appDefinitions)
      ? 'app_definitions_v1' : 'unknown';
  }
  const data = envelope.data;
  return data && typeof data === 'object' &&
    typeof data.hasRootSsl === 'boolean' && typeof data.forceSsl === 'boolean' &&
    typeof data.rootDomain === 'string' && typeof data.captainSubDomain === 'string'
    ? 'system_info_v1' : 'unknown';
}

const originalLoad = Module._load;
Module._load = function guardedLoad(request, parent, isMain) {
  const exported = originalLoad.apply(this, arguments);
  if (request !== 'request-promise' || exported.__caproverReadonlyGuarded) return exported;
  for (const methodName of ['get', 'post', 'patch']) {
    if (typeof exported[methodName] !== 'function') continue;
    const original = exported[methodName].bind(exported);
    exported[methodName] = function guardedPromiseRequest(uri, options) {
      const evidence = validateLogical(methodName.toUpperCase(), uri);
      const safe = Object.assign({}, options || {}, {
        followRedirect: false,
        followAllRedirects: false,
        maxRedirects: 0,
        strictSSL: true,
      });
      const promise = original(uri, safe);
      promise.then(
        (value) => emit({
          type: 'api_response', endpoint: evidence.endpoint, sequence: evidence.sequence,
          captainStatus: Number.isInteger(value && value.status) ? value.status : null,
          schema: schemaFor(evidence.endpoint, value),
        }),
        (error) => emit({
          type: 'request_error', endpoint: evidence.endpoint, sequence: evidence.sequence,
          code: networkErrorCode(error),
        })
      );
      return promise;
    };
  }
  Object.defineProperty(exported, '__caproverReadonlyGuarded', {value: true});
  return exported;
};

emit({type: 'guard_ready', guardVersion: GUARD_VERSION, nodeVersion: process.versions.node});
