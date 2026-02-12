var EventType = /* @__PURE__ */ ((EventType2) => {
  EventType2["META"] = "meta_event";
  EventType2["REQUEST"] = "request";
  EventType2["NOTICE"] = "notice";
  EventType2["MESSAGE"] = "message";
  EventType2["MESSAGE_SENT"] = "message_sent";
  return EventType2;
})(EventType || {});

let actions = void 0;
let startTime = Date.now();
const plugin_init = async (_core, _obContext, _actions, _instance) => {
  console.log("[Plugin: builtin] NapCat 内置插件已初始化");
  actions = _actions;
};
const plugin_onmessage = async (adapter, _core, _obCtx, event, _actions, instance) => {
  if (event.post_type !== EventType.MESSAGE || !event.raw_message.startsWith("#napcat")) {
    return;
  }
  try {
    const versionInfo = await getVersionInfo(adapter, instance.config);
    if (!versionInfo) return;
    const message = formatVersionMessage(versionInfo);
    await sendMessage(event, message, adapter, instance.config);
    console.log("[Plugin: builtin] 已回复版本信息");
  } catch (error) {
    console.error("[Plugin: builtin] 处理消息时发生错误:", error);
  }
};
async function getVersionInfo(adapter, config) {
  if (!actions) return null;
  try {
    const data = await actions.call("get_version_info", void 0, adapter, config);
    return {
      appName: data.app_name,
      appVersion: data.app_version,
      protocolVersion: data.protocol_version
    };
  } catch (error) {
    console.error("[Plugin: builtin] 获取版本信息失败:", error);
    return null;
  }
}
function formatUptime(ms) {
  const seconds = Math.floor(ms / 1e3);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);
  if (days > 0) {
    return `${days}天 ${hours % 24}小时 ${minutes % 60}分钟`;
  } else if (hours > 0) {
    return `${hours}小时 ${minutes % 60}分钟`;
  } else if (minutes > 0) {
    return `${minutes}分钟 ${seconds % 60}秒`;
  } else {
    return `${seconds}秒`;
  }
}
function formatVersionMessage(info) {
  const uptime = Date.now() - startTime;
  return `NapCat 信息
版本: ${info.appVersion}
平台: ${process.platform}${process.arch === "x64" ? " (64-bit)" : ""}
运行时间: ${formatUptime(uptime)}`;
}
async function sendMessage(event, message, adapter, config) {
  if (!actions) return;
  const params = {
    message,
    message_type: event.message_type,
    ...event.message_type === "group" && event.group_id ? { group_id: String(event.group_id) } : {},
    ...event.message_type === "private" && event.user_id ? { user_id: String(event.user_id) } : {}
  };
  try {
    await actions.call("send_msg", params, adapter, config);
  } catch (error) {
    console.error("[Plugin: builtin] 发送消息失败:", error);
  }
}

export { plugin_init, plugin_onmessage };
