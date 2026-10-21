// Private inspection report envelope. No external dependencies or model calls.
import { generateKeyPairSync, createPublicKey, createPrivateKey, diffieHellman,
  hkdfSync, randomBytes, createCipheriv, createDecipheriv } from 'node:crypto';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const AAD = Buffer.from('jarvis-vps-inspection-v1');
const MAX = 1048576;
const b64 = value => Buffer.from(value).toString('base64');
function decode(value, max, expected) {
  if (typeof value !== 'string' || !/^[A-Za-z0-9+/]*={0,2}$/.test(value) || value.length > max * 2) throw Error('Invalid envelope');
  const result = Buffer.from(value, 'base64');
  if (result.length > max || (expected && result.length !== expected) || result.toString('base64') !== value) throw Error('Invalid envelope');
  return result;
}

export function generateRecipient() {
  const pair = generateKeyPairSync('x25519');
  return {
    publicKey: b64(pair.publicKey.export({ type: 'spki', format: 'der' })),
    privateKey: pair.privateKey.export({ type: 'pkcs8', format: 'pem' }),
  };
}

export function seal(plaintext, recipient) {
  if (!Buffer.isBuffer(plaintext) || plaintext.length > MAX || plaintext.length === 0) throw Error('Report size rejected');
  JSON.parse(plaintext.toString('utf8')); // Do not upload an encrypted SSH error as a report.
  const publicKey = createPublicKey({ key: decode(recipient, 128), type: 'spki', format: 'der' });
  if (publicKey.asymmetricKeyType !== 'x25519') throw Error('Invalid recipient');
  const ephemeral = generateKeyPairSync('x25519');
  const salt = randomBytes(32), iv = randomBytes(12);
  const secret = diffieHellman({ privateKey: ephemeral.privateKey, publicKey });
  const key = Buffer.from(hkdfSync('sha256', secret, salt, AAD, 32));
  const cipher = createCipheriv('aes-256-gcm', key, iv);
  cipher.setAAD(AAD);
  const ciphertext = Buffer.concat([cipher.update(plaintext), cipher.final()]);
  key.fill(0); secret.fill(0);
  return { version: 1, ephemeral: b64(ephemeral.publicKey.export({ type: 'spki', format: 'der' })),
    salt: b64(salt), iv: b64(iv), tag: b64(cipher.getAuthTag()), ciphertext: b64(ciphertext) };
}

export function open(envelope, privatePem) {
  if (!envelope || envelope.version !== 1 || Object.keys(envelope).sort().join(',') !== 'ciphertext,ephemeral,iv,salt,tag,version') throw Error('Invalid envelope');
  const privateKey = createPrivateKey(privatePem);
  const publicKey = createPublicKey({ key: decode(envelope.ephemeral, 128), type: 'spki', format: 'der' });
  if (privateKey.asymmetricKeyType !== 'x25519' || publicKey.asymmetricKeyType !== 'x25519') throw Error('Invalid key');
  const secret = diffieHellman({ privateKey, publicKey });
  const key = Buffer.from(hkdfSync('sha256', secret, decode(envelope.salt, 32, 32), AAD, 32));
  try {
    const decipher = createDecipheriv('aes-256-gcm', key, decode(envelope.iv, 12, 12));
    decipher.setAAD(AAD); decipher.setAuthTag(decode(envelope.tag, 16, 16));
    return Buffer.concat([decipher.update(decode(envelope.ciphertext, MAX)), decipher.final()]);
  } finally { key.fill(0); secret.fill(0); }
}

async function main() {
  const [action, argument, keyPath] = process.argv.slice(2);
  if (action === 'keygen') {
    if (!argument) throw Error();
    const target = resolve(argument);
    mkdirSync(target, { mode: 0o700 }); // Never overwrite an existing key directory.
    const pair = generateRecipient();
    writeFileSync(resolve(target, 'recipient-private.pem'), pair.privateKey, { mode: 0o600, flag: 'wx' });
    writeFileSync(resolve(target, 'recipient-public.txt'), pair.publicKey + '\n', { mode: 0o600, flag: 'wx' });
    process.stdout.write(pair.publicKey + '\n'); // Public recipient only.
  } else if (action === 'seal') {
    const recipient = process.env.VPS_REPORT_RECIPIENT;
    if (!recipient) throw Error();
    let length = 0; const chunks = [];
    for await (const chunk of process.stdin) {
      length += chunk.length;
      if (length > MAX) throw Error();
      chunks.push(chunk);
    }
    process.stdout.write(JSON.stringify(seal(Buffer.concat(chunks), recipient)) + '\n');
  } else if (action === 'open') {
    if (!argument || !keyPath) throw Error();
    const data = readFileSync(argument);
    if (data.length > MAX * 2) throw Error();
    process.stdout.write(open(JSON.parse(data), readFileSync(keyPath, 'utf8')));
  } else throw Error();
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main().catch(() => { console.error('Report operation failed. Check command, key, envelope, and size.'); process.exitCode = 1; });
}
