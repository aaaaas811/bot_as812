import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const moduleUrl = new URL('../plugins/qq_task_reminder/desktop/index.mjs', import.meta.url);
const config = { account: '123', groups: ['456'], url: 'https://example.invalid/events', token: 'secret' };
const event = { post_type: 'message', message_type: 'group', self_id: 123, group_id: 456,
  message_id: 10, time: 1792749600, sender: { nickname: 'private data' },
  message: [{ type: 'text', data: { text: '明天交报告' } }, { type: 'image', data: { url: 'private-url' } }] };

test('desktop filters other conversations before queueing or sending', async () => {
  const { selectEvent } = await import(moduleUrl);
  assert.equal(selectEvent({ ...event, group_id: 999 }, config), null);
  assert.equal(selectEvent({ ...event, self_id: 999 }, config), null);
  assert.equal(selectEvent({ ...event, message_type: 'private' }, config), null);
  const selected = selectEvent(event, config);
  assert.deepEqual(selected.message, [{ type: 'text', data: { text: '明天交报告' } }]);
  assert.equal(selected.sender, undefined);
});

test('failed delivery remains on disk and survives forwarder restart', async (t) => {
  const { Forwarder } = await import(moduleUrl);
  const data = path.join(root, 'data');
  await fs.mkdir(data, { recursive: true });
  const dir = await fs.mkdtemp(path.join(data, 'qq-forwarder-test-'));
  t.after(async () => {
    assert.equal(path.dirname(path.resolve(dir)), data);
    await fs.rm(dir, { recursive: true });
  });
  const failing = new Forwarder(config, dir, async () => { throw new Error('offline'); });
  await failing.enqueue(event);
  await failing.enqueue({ ...event, group_id: 999 });
  await assert.rejects(failing.flush(), /offline/);
  assert.equal((await fs.readdir(dir)).filter(name => name.endsWith('.json')).length, 1);
  const sent = [];
  const restored = new Forwarder(config, dir, async (url, options) => {
    sent.push(JSON.parse(options.body));
    return { ok: true, json: async () => ({ ok: true }) };
  });
  await restored.flush();
  assert.equal(sent.filter(item => item.post_type === 'message').length, 1);
  assert.equal((await fs.readdir(dir)).filter(name => name.endsWith('.json')).length, 0);
});

test('mentions retain task applicability without uploading media', async () => {
  const { selectEvent } = await import(moduleUrl);
  const selected = selectEvent({ ...event, message: [
    { type: 'at', data: { qq: '789' } }, { type: 'text', data: { text: '请提交报告' } }
  ] }, config);
  assert.equal(selected.message.map(segment => segment.data.text).join(''), '[at:789]请提交报告');
});

test('an HTTP 200 without application acknowledgement is not delivery', async () => {
  const { Forwarder } = await import(moduleUrl);
  const forwarder = new Forwarder(config, '', async () => ({ ok: true, json: async () => ({}) }));
  await assert.rejects(forwarder.post(event), /acknowledge/);
});
