#!/usr/bin/env node
// Stdin/stdout bridge between AA's Python CLI and `@banodoco/timeline-ops`.
//
// Reads a JSON request `{timeline, version, op, args}` from stdin, dispatches
// `op` to the matching primitive (`addClip`, `moveClip`, `setTimelineTheme`),
// and writes `{timeline, version, op, changed, detail}` to stdout. Exits
// non-zero with a JSON error object on stderr if the op is unknown or the
// stdin shape is invalid.
//
// Sprint-08 contract: AA's edit verbs (T11) shell out here instead of using
// `createTimelineCommandRunner`; the primitives `addClip`, `moveClip`, and
// `setTimelineTheme` ARE exported by the local package and are the canonical
// authoring API.

import {addClip, moveClip, setTimelineTheme} from '@banodoco/timeline-ops';

const SUPPORTED_OPS = new Set(['add-clip', 'move-clip', 'set-theme']);

const readStdin = () =>
  new Promise((resolve, reject) => {
    let data = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (chunk) => {
      data += chunk;
    });
    process.stdin.on('end', () => resolve(data));
    process.stdin.on('error', reject);
  });

const fail = (message, extra = {}) => {
  process.stderr.write(`${JSON.stringify({error: message, ...extra})}\n`);
  process.exit(1);
};

const dispatch = (op, timeline, args) => {
  if (op === 'add-clip') {
    const clip = args.clip;
    if (!clip || typeof clip !== 'object') {
      fail('add-clip requires args.clip object');
    }
    const position = typeof args.position === 'number' ? args.position : undefined;
    return addClip(timeline, clip, position);
  }
  if (op === 'move-clip') {
    if (typeof args.clipId !== 'string' || args.clipId === '') {
      fail('move-clip requires args.clipId string');
    }
    if (typeof args.newPosition !== 'number') {
      fail('move-clip requires args.newPosition number');
    }
    return moveClip(timeline, args.clipId, args.newPosition);
  }
  if (op === 'set-theme') {
    if (typeof args.themeId !== 'string' || args.themeId === '') {
      fail('set-theme requires args.themeId string');
    }
    return setTimelineTheme(timeline, args.themeId);
  }
  fail(`unsupported op: ${op}`, {supported: [...SUPPORTED_OPS]});
};

const main = async () => {
  const raw = await readStdin();
  if (!raw.trim()) {
    fail('empty stdin; expected {timeline, version, op, args} JSON');
  }
  let request;
  try {
    request = JSON.parse(raw);
  } catch (error) {
    fail(`invalid JSON on stdin: ${error.message}`);
  }
  const {timeline, version, op, args = {}} = request ?? {};
  if (!timeline || typeof timeline !== 'object') {
    fail('request.timeline must be an object');
  }
  if (!SUPPORTED_OPS.has(op)) {
    fail(`unsupported op: ${op}`, {supported: [...SUPPORTED_OPS]});
  }
  const result = dispatch(op, timeline, args);
  const response = {
    timeline: result.config,
    version,
    op,
    changed: result.changed,
    detail: result.detail,
  };
  process.stdout.write(`${JSON.stringify(response)}\n`);
};

main().catch((error) => {
  fail(`ops_helper failed: ${error.stack ?? error.message ?? String(error)}`);
});
