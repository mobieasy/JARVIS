import { test } from 'node:test';
import assert from 'node:assert/strict';
import { generateRecipient, seal, open } from './report_crypto.mjs';

test('report roundtrip uses recipient private key and hides plaintext', () => {
  const recipient = generateRecipient();
  const report = Buffer.from(JSON.stringify({ synthetic: 'PRIVATE_FIXTURE', language: 'ગુજરાતી' }));
  const encrypted = seal(report, recipient.publicKey);
  assert.equal(open(encrypted, recipient.privateKey).toString(), report.toString());
  assert.ok(!JSON.stringify(encrypted).includes('PRIVATE_FIXTURE'));
});
test('wrong recipient and modified ciphertext are rejected', () => {
  const a = generateRecipient(), b = generateRecipient();
  const envelope = seal(Buffer.from('{}'), a.publicKey);
  assert.throws(() => open(envelope, b.privateKey));
  const changed = Buffer.from(envelope.ciphertext, 'base64'); changed[0] ^= 1;
  assert.throws(() => open({ ...envelope, ciphertext: changed.toString('base64') }, a.privateKey));
});
test('nonce, tag, salt and version tampering is rejected', () => {
  const pair = generateRecipient();
  const envelope = seal(Buffer.from('{}'), pair.publicKey);
  for (const field of ['iv', 'tag', 'salt']) {
    const changed = Buffer.from(envelope[field], 'base64'); changed[0] ^= 1;
    assert.throws(() => open({ ...envelope, [field]: changed.toString('base64') }, pair.privateKey));
  }
  assert.throws(() => open({ ...envelope, version: 2 }, pair.privateKey));
  assert.throws(() => open({ ...envelope, unexpected: true }, pair.privateKey));
});
test('identical reports produce distinct envelopes', () => {
  const pair = generateRecipient();
  assert.notDeepEqual(seal(Buffer.from('{}'), pair.publicKey), seal(Buffer.from('{}'), pair.publicKey));
});
test('malformed input, keys and oversized reports fail closed', () => {
  const pair = generateRecipient();
  assert.throws(() => seal(Buffer.from('SSH error'), pair.publicKey));
  assert.throws(() => seal(Buffer.from('{}'), 'not a key'));
  assert.throws(() => seal(Buffer.alloc(1048577), pair.publicKey));
  const envelope = seal(Buffer.from('{}'), pair.publicKey);
  assert.throws(() => open({ ...envelope, ephemeral: 'bad!' }, pair.privateKey));
});
