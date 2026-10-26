import fs from 'node:fs/promises';
import path from 'node:path';
import { createHash, randomUUID } from 'node:crypto';

// Runs inside NapCat; does not start Node, Python or another QQ.
export function selectEvent(event, config) {
  if (event?.post_type !== 'message' || event.message_type !== 'group'
      || String(event.self_id) !== String(config.account)
      || !config.groups.map(String).includes(String(event.group_id))
      || !Array.isArray(event.message) || event.message_id == null || !Number.isFinite(event.time)) return null;
  const message = event.message.filter(segment => segment.type === 'text' || segment.type === 'at')
    .map(segment => ({ type: 'text', data: { text: segment.type === 'at'
      ? `[at:${String(segment.data?.qq ?? '')}]` : String(segment.data?.text ?? '') } }));
  if (!message.some(segment => segment.data.text.trim())) return null;
  return { post_type: 'message', message_type: 'group', self_id: event.self_id,
    group_id: event.group_id, message_id: event.message_id, time: event.time, message };
}

export class Forwarder {
  constructor(config, directory, send = globalThis.fetch) {
    this.config = config;
    this.directory = directory;
    this.send = send;
    this.active = null;
  }

  async enqueue(event) {
    const selected = selectEvent(event, this.config);
    if (!selected) return;
    await fs.mkdir(this.directory, { recursive: true });
    const id = createHash('sha256').update(`${event.group_id}:${event.message_id}`).digest('hex');
    const name = `${String(event.time).padStart(12, '0')}-${id}.json`;
    const temporary = path.join(this.directory, `${randomUUID()}.tmp`);
    await fs.writeFile(temporary, JSON.stringify(selected), { mode: 0o600 });
    await fs.rename(temporary, path.join(this.directory, name));
  }

  async post(event) {
    const result = await this.send(this.config.url, { method: 'POST', redirect: 'error',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${this.config.token}` },
      body: JSON.stringify(event), signal: AbortSignal.timeout(15000) });
    if (!result.ok) throw new Error('Server did not accept the event');
    const acknowledgement = await result.json();
    if (acknowledgement.ok !== true) throw new Error('Server did not acknowledge the event');
  }

  async flush() {
    if (this.active) return this.active;
    this.active = this.drain();
    try { await this.active; } finally { this.active = null; }
  }

  async drain() {
    await fs.mkdir(this.directory, { recursive: true });
    await this.post({ post_type: 'meta_event', self_id: this.config.account });
    const files = (await fs.readdir(this.directory)).filter(name => name.endsWith('.json')).sort().slice(0, 50);
    for (const name of files) {
      const file = path.join(this.directory, name);
      const event = JSON.parse(await fs.readFile(file, 'utf8'));
      const selected = selectEvent(event, this.config);
      if (selected) await this.post(selected);
      // Delete this queue file only after acknowledgement or removal from the allowlist.
      await fs.unlink(file);
    }
  }
}

let forwarder;
let timer;
const pendingWrites = new Set();

export async function plugin_init(ctx) {
  let config;
  try { config = JSON.parse(await fs.readFile(ctx.configPath, 'utf8')); }
  catch (error) {
    if (error.code !== 'ENOENT') throw error;
    await fs.mkdir(path.dirname(ctx.configPath), { recursive: true });
    await fs.writeFile(ctx.configPath, JSON.stringify({ enabled: false, account: '', groups: [], url: '', token: '' }, null, 2));
    ctx.logger.info(`请填写采集配置并重新加载插件：${ctx.configPath}`);
    return;
  }
  if (!config.enabled) return;
  if (!config.account || !Array.isArray(config.groups) || !config.groups.length || !config.token
      || !/^https?:\/\//.test(config.url)) throw new Error('请填写账号、群白名单、HTTP(S) 地址和 token');
  forwarder = new Forwarder(config, path.join(ctx.dataPath, 'outbox'));
  const flush = () => forwarder.flush().catch(() => ctx.logger.warn('任务服务器暂不可达，消息已保留，30 秒后重试'));
  timer = setInterval(flush, 30000);
  timer.unref?.();
  void flush();
}

export async function plugin_onmessage(ctx, event) {
  if (!forwarder) return;
  const write = forwarder.enqueue(event);
  pendingWrites.add(write);
  try { await write; }
  catch { ctx.logger.error('任务消息写入失败，请检查磁盘空间和采集数据目录权限'); }
  finally { pendingWrites.delete(write); }
}

export async function plugin_cleanup() {
  clearInterval(timer);
  await Promise.allSettled([...pendingWrites]);
  if (forwarder?.active) await forwarder.active.catch(() => {});
  forwarder = undefined;
}
