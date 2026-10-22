import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
import test from 'node:test';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const workflowPath = path.join(repoRoot, '.github/workflows/auto-assign.yml');
const workflow = fs.readFileSync(workflowPath, 'utf8');

function extractFunction(source, name) {
  const marker = `function ${name}(`;
  const start = source.indexOf(marker);
  if (start === -1) {
    throw new Error(`${name} not found in ${workflowPath}`);
  }
  const braceStart = source.indexOf('{', start);
  if (braceStart === -1) {
    throw new Error(`${name} has no body`);
  }
  let depth = 0;
  for (let i = braceStart; i < source.length; i++) {
    const ch = source[i];
    if (ch === '{') depth += 1;
    else if (ch === '}') {
      depth -= 1;
      if (depth === 0) {
        return source.slice(start, i + 1);
      }
    }
  }
  throw new Error(`${name} is unclosed`);
}

function loadFunction(name) {
  const src = extractFunction(workflow, name);
  return new Function(`${src}\nreturn ${name};`)();
}

const isExplicitVolunteerRequest = loadFunction('isExplicitVolunteerRequest');
const skipReasonForAssignees = loadFunction('skipReasonForAssignees');

const shouldMatch = [
  'please assign me',
  'Please assign me to this issue.',
  'assign me to this',
  "I'd like to work on this",
  'I would like to work on this',
  'I can take this',
  'can I take this?',
  'Can I take this',
  "I'll pick this up",
  'I will pick this up.',
  'interested in working on this',
  '/assign',
  '/assign me',
  'Please /assign me',
];

const shouldNotMatch = [
  // Real misfire: hedge containing "pick this up"
  "I'll circle back if I can pick this up",
  'circle back if I can pick this up',
  'if I can pick this up',
  "please don't assign me",
  "don't assign me",
  'do not assign me',
  'unassign me',
  'please unassign me',
  'The assignment of ids should stay stable.',
  'this PR claims that X',
  'This PR claims that the cache is optional.',
  'file a claim with insurance',
  'claim-check the payload',
  'Please assign someone else.',
  'take this with a grain of salt',
  'work on this later maybe',
  'pick this up from the queue in the worker',
];

test('matches explicit volunteer requests', () => {
  for (const body of shouldMatch) {
    assert.equal(isExplicitVolunteerRequest(body), true, `expected a match: ${JSON.stringify(body)}`);
  }
});

test('rejects hedges, negations, and incidental wording', () => {
  for (const body of shouldNotMatch) {
    assert.equal(isExplicitVolunteerRequest(body), false, `expected no match: ${JSON.stringify(body)}`);
  }
});

test('dajiaohuang hedge on maintainer-skills-lab#86 does not volunteer', () => {
  const body = "I'll circle back if I can pick this up";
  assert.equal(isExplicitVolunteerRequest(body), false);
});

test('slash assign is accepted and assignment/claims are not', () => {
  assert.equal(isExplicitVolunteerRequest('/assign'), true);
  assert.equal(isExplicitVolunteerRequest('/assign me'), true);
  assert.equal(isExplicitVolunteerRequest('/assignment'), false);
  assert.equal(isExplicitVolunteerRequest('this PR claims that X'), false);
});

// skipReasonForAssignees is the workflow's already-assigned gate:
// any assignee other than the commenter means do nothing (no comment, no addAssignees).
test('skips when someone else is already assigned', () => {
  assert.equal(
    skipReasonForAssignees('dajiaohuang', ['octocat']),
    'Skipping auto-assign for dajiaohuang: issue already assigned to octocat.'
  );
  assert.equal(skipReasonForAssignees('alice', ['alice']), 'alice is already assigned.');
  assert.equal(skipReasonForAssignees('alice', []), null);
  assert.equal(skipReasonForAssignees('alice', null), null);
});
