# 树莓派 Linux 部署与更新

目标：64 位 ARM Linux（`uname -m` 应为 `aarch64`），Python >= 3.12。
当前 Windows 工作环境为 Python 3.13.2 / NcatBot 5.5.6。
以下目录统一使用 `~/bot_as812`，SSH 地址使用 `as811@10.208.76.83`。
RealVNC 用于查看树莓派桌面和扫码，文件传输、部署和更新通过 SSH 完成。

本次树莓派连接 `SEU-WLAN`，需要先完成校园网认证。仅连接 Wi-Fi 或开启代理
不能代替校园网认证；HTTP 请求重定向到 `10.80.128.2` 登录页、HTTPS 超时，
说明应先在树莓派浏览器完成校园网登录。重启或 IP 改变后可能需要重新认证。
系统时间也必须准确，当前代理的 VMess 认证依赖时间同步。

## 1. 首次迁移

先在 Windows 停止正在运行的 bot，保证 ChromaDB 和业务数据复制一致。
在项目目录的 PowerShell 中执行：

```powershell
cd D:\_store\bot_as812
.venv\Scripts\python.exe deploy\bundle.py --with-state --output dist\bot-migration.tar.gz
scp dist\bot-migration.tar.gz as811@10.208.76.83:~/bot-migration.tar.gz
ssh as811@10.208.76.83
```

首次包包含根配置、插件配置、RAG 知识库、怪物资料、运行数据、业务资源，
包括当前未提交的插件文件。包内有 API 密钥及业务数据，只用于自己的树莓派，
不要上传 GitHub。不会打包 Windows `.venv`、Windows NapCat、日志或图片缓存。
`.env` 文件不打包；如自行增加了此类配置，请单独迁移。

在树莓派终端执行环境检查：

```bash
uname -m
cat /etc/os-release
python3 --version
df -h ~
free -h
```

若是 `armv7l` / 32 位系统，需先更换为 64 位 Raspberry Pi OS；这一步涉及系统重装，
不要直接运行下面的安装命令。先检查目标是否已有 bot，已有部署需备份后另行合并。

对 Raspberry Pi OS / Debian / Ubuntu，安装系统依赖：

```bash
sudo apt update
sudo apt install -y python3-venv python3-tk curl xz-utils git screen xvfb xauth fonts-noto-cjk
test ! -e "$HOME/bot_as812"
mkdir -m 700 "$HOME/bot_as812"
tar -xzf "$HOME/bot-migration.tar.gz" -C "$HOME/bot_as812"
cd "$HOME/bot_as812"
```

逐步执行；如果 `test` 报错，说明目标目录已经存在，先处理已有部署。
Debian 系中文字体一般位于 `opentype/noto`。怪物表格渲染器还查找旧的
`truetype/noto` 路径，可在确认源字体存在后建立兼容链接：

```bash
test -f /usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc
sudo mkdir -p /usr/share/fonts/truetype/noto
sudo ln -sfn /usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc /usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc
```

若系统 `python3` >= 3.12，可以直接创建虚拟环境：

```bash
python3 -m venv .venv
```

若系统 Python 为 3.11（例如 Bookworm），使用独立 uv 环境安装 Python 3.13，
不替换系统 Python：

```bash
python3 -m venv "$HOME/.local/share/bot-uv"
"$HOME/.local/share/bot-uv/bin/python" -m pip install uv
"$HOME/.local/share/bot-uv/bin/uv" python install 3.13
"$HOME/.local/share/bot-uv/bin/uv" venv --python 3.13 .venv
"$HOME/.local/share/bot-uv/bin/uv" pip install --python .venv/bin/python pip
```

安装 Linux 专用依赖：

```bash
.venv/bin/python -m pip install -r deploy/requirements-linux.txt
.venv/bin/python -m pip check
```

本次目标机已有离线依赖目录 `~/bot-wheels`。如果外网不可用，使用：

```bash
.venv/bin/python -m pip install --no-index --find-links "$HOME/bot-wheels" -r deploy/requirements-linux.txt
.venv/bin/python -m pip check
```

更新时也可把后面的在线安装命令换成此离线命令；增加或修改依赖版本时，
需先下载对应 Linux ARM64 / Python 3.13 的 wheel 并补充到该目录。

不要再安装根目录或 `as812` 插件的 requirements：其 `aiohttp==3.11.13`
与 NcatBot 5.5.6 的 `aiohttp>=3.13.4` 要求冲突。Linux 清单统一了已启用插件的依赖。

## 2. 配置、NapCat 和登录

迁移配置后，关闭后台服务中不适合交互执行的依赖安装：

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
import yaml
path = Path('config.yaml')
config = yaml.safe_load(path.read_text(encoding='utf-8'))
config['check_ncatbot_update'] = False
config['plugin']['auto_install_pip_deps'] = False
for adapter in config.get('adapters', []):
    if adapter.get('type') == 'napcat':
        adapter.setdefault('config', {})['enable_update_check'] = False
path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding='utf-8')
PY
```

如启用了本地 Ollama，迁移 Python SDK 不会迁移模型和 Ollama 服务。
需要在树莓派另行部署模型，或设置 `OLLAMA_HOST` 指向原模型服务器。
小智桥接目前指向 `ws://172.22.132.125:8000/xiaozhi/v1/`，需确认树莓派能访问该地址。
外部 API、B 站登录信息和 Steam 代理同样需要在树莓派核验。
本次 Steam 直连超时，已在树莓派插件配置中启用代理 `http://127.0.0.1:7897`，
认证后的 Steam 玩家查询返回 HTTP 200。需保持本机 Clash 运行。
小智服务器当前连接超时；用户暂时不需要该功能，插件保持启动时默认关闭桥接。

在树莓派桌面终端或 SSH 终端前台启动：

```bash
cd ~/bot_as812
.venv/bin/python main.py
```

框架首次启动会引导安装 **Linux/ARM64 的 NapCat 和 QQ**，按安装提示操作；
系统安装可能需要 sudo。不要复制 Windows `napcat` / `NapCat.Shell` 目录。
若树莓派上已安装 NapCat，先确认配置令牌、QQ 号和端口与 `config.yaml` 一致。

在 RealVNC 中用树莓派浏览器打开 `http://localhost:6099`，按 WebUI 提示用手机 QQ 扫码。
也可在 Windows 另开 PowerShell 建立 SSH 隧道，然后访问本机 `http://localhost:6099`：

```powershell
ssh -N -L 6099:127.0.0.1:6099 as811@10.208.76.83
```

验证 QQ 账号为配置中的 bot 账号、WebSocket 已连接、预期插件已加载，
并在 QQ 中检查一次已有查询指令及图片渲染。通过后用 Ctrl+C 停止前台 bot。
迁移后保持 Windows bot 停止，避免同一账号的两个实例同时处理消息。

## 3. 开机自启与日志

当前树莓派复用 `~/Napcat/opt/QQ` 中的 rootless QQ/NapCat，协议端与 bot
分别使用用户级 systemd 服务，以普通 Linux 用户运行。NapCat 当前版本为 4.18.9。框架配置中的 NapCat
`skip_setup` 已设为 `true`，通过已有服务连接。迁移了 WS/WebUI 令牌、设置了
仅监听 `127.0.0.1`，旧配置备份位于 `~/bot-backups/napcat-config-before-migration.tar.gz`。

项目提供的 bot 服务依赖 `napcat@3024473284.service`，更换 QQ 账号时需同步
修改该依赖和 NapCat 实例账号；若使用其他安装路径，还需修改 NapCat 单元的启动路径。

```bash
mkdir -p ~/.config/systemd/user
cp ~/bot_as812/deploy/napcat@.service ~/.config/systemd/user/
cp ~/bot_as812/deploy/bot_as812.service ~/.config/systemd/user/
sudo loginctl enable-linger "$USER"
systemctl --user daemon-reload
systemctl --user enable --now napcat@3024473284
systemctl --user enable --now bot_as812
systemctl --user status bot_as812 --no-pager
sudo journalctl _SYSTEMD_USER_UNIT=bot_as812.service -n 100 --no-pager
```

启用 linger 后，断开 SSH / RealVNC 或重启系统，用户服务仍可运行。
本机普通 `journalctl --user` 未返回服务日志，因此使用上述 sudo 查询命令。
服务失败会间隔 15 秒重试，5 分钟内最多启动 5 次；修复配置后可执行
`systemctl --user reset-failed bot_as812` 再启动。

后台服务没有桌面会话，可视化面板需要在 RealVNC 的桌面终端另行打开：

```bash
cd ~/bot_as812
.venv/bin/python plugins/as812/visual_panel.py
```

常用操作：

```bash
systemctl --user restart bot_as812
systemctl --user stop bot_as812
systemctl --user start bot_as812
sudo journalctl _SYSTEMD_USER_UNIT=bot_as812.service -f
```

`systemctl --user restart bot_as812` 只重启 Python bot；NapCat 保持运行，
可继续使用已登录的 QQ 会话。需要重启协议端时另行执行：

```bash
systemctl --user restart napcat@3024473284
```

## 4. 之后如何推送更新

日常采用 **Windows 打包代码 → SCP 上传 → 树莓派备份、解压、重启**。
不需要先推 GitHub；未提交的代码也会包含在更新包中。

Windows 项目目录执行（不加 `--with-state`）：

```powershell
cd D:\_store\bot_as812
.venv\Scripts\python.exe deploy\bundle.py --output dist\bot-code.tar.gz
scp dist\bot-code.tar.gz as811@10.208.76.83:~/bot-code.tar.gz
ssh as811@10.208.76.83
```

在树莓派终端复制执行下列块；任何步骤失败都会停止后续操作：

```bash
bash <<'SH'
set -e
cd "$HOME/bot_as812"
tar -tzf "$HOME/bot-code.tar.gz" >/dev/null
systemctl --user stop bot_as812
mkdir -p "$HOME/bot-backups"
chmod 700 "$HOME/bot-backups"
backup="$HOME/bot-backups/bot-$(date +%Y%m%d-%H%M%S).tar.gz"
tar --exclude='bot_as812/.venv' --exclude='bot_as812/logs' \
    --exclude='*/logs' --exclude='*/__pycache__' --exclude='*/image_cache' \
    -czf "$backup" -C "$HOME" bot_as812
echo "Backup: $backup"
tar -xzf "$HOME/bot-code.tar.gz" -C "$HOME/bot_as812"
.venv/bin/python -m pip install -r deploy/requirements-linux.txt
.venv/bin/python -m pip check
cp deploy/bot_as812.service "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user restart bot_as812
systemctl --user status bot_as812 --no-pager
SH
sudo journalctl _SYSTEMD_USER_UNIT=bot_as812.service -n 100 --no-pager
```

代码更新不会覆盖根配置、插件配置、`data/`、`rag_data/`、`memory/` 或数据库，
也不会复制日志和 Windows 环境。新增插件需相应补充 Linux 依赖及目标机配置；
JSON/YAML 文件默认不更新，`*.example.json` 和 `assets/` 内静态资源除外。
任务提醒插件的 `config.toml` 同样保留；`config.example.toml` 和桌面转发插件的
`package.json` 随代码发布。QQ 任务提醒未填写配置时保持关闭。
校园讲座插件需要 `cryptography>=41`，已列入 Linux 依赖清单。
怪物资料和语录等 `data/` 内资源需单独更新。解压采用覆盖方式，代码删除或插件改名
需在目标上单独处理；不会自动删除树莓派文件。

如果启动失败，先看日志。可停止服务，用上面的备份覆盖恢复旧代码和配置，
再根据恢复后的 Linux requirements 安装依赖并启动；恢复备份会恢复旧运行数据，
务必先保留更新后的数据。虚拟环境未包含在备份中，依赖安装过程可能改变间接依赖，
因此这不是完整环境快照。

GitHub 上的 Linux 部署分支为 `codex/linux-raspberry-pi`。推送该分支后，
树莓派仍通过上面的代码包流程更新，GitHub 推送不会自动更新正在运行的 bot。
在该分支的工作副本中，先检查并只提交选定代码：

```powershell
git status --short
git switch codex/linux-raspberry-pi
git add deploy README.md plugins/as812/__init__.py tests/test_as812_import.py tests/test_deployment_bundle.py
# 另外 git add 本次实际修改的插件代码，避免 git add . 把已有数据库变化带入提交
git commit -m "Describe the bot update"
git push origin codex/linux-raspberry-pi
```

当前仓库包含已跟踪的 NapCat 文件和 RAG 数据库，且本地存在运行数据变化。
在拆分代码与运行数据之前，树莓派采用上述代码包更新流程，避免直接 `git pull`
把仓库中的数据库覆盖到实际运行环境。

## 验收与当前进度

迁移完成需实际确认：ARM64 / Python 版本、`pip check`、QQ 登录与 WS 连接、
插件加载、QQ 指令回复、中文图片，以及 systemd 重启后的日志。
2026-10-08 已通过 SSH 确认目标为 Debian 13 / ARM64 / Python 3.13.5。
中文字体和 Linux Python 依赖已安装，目标机 `pip check` 通过，NcatBot、
ChromaDB、aiohttp、Ollama、Pillow、NumPy 导入通过。
依赖从 Windows 下载公开 ARM64 wheel 并在目标机离线安装；wheel 保存在 `~/bot-wheels`。
系统时钟从错误的 6 月日期校准至当前日期，NTP 已保持启用。
已配置可达 NTP 服务器，并将未接网线的 eth0 设为不阻塞联网判定，
配置分别保存于 `/etc/systemd/timesyncd.conf.d/bot-pi.conf` 和
`/etc/systemd/network/04-eth.network.d/online.conf`。

已获用户授权上传全部配置与业务数据；迁移包已上传、SHA256 校验并解压。
校园网通过用户提供的认证方式登录，直连和代理 PyPI 均返回 HTTP 200。
已修正同名包冲突：功能插件需要 `uapi-sdk-python==0.1.5`，而不是 PyPI 的 `uapi`。
7 个启用插件在目标机导入全部通过，NapCat 服务启动、WebUI 访问及二维码获取通过。
QQ 3024473284 已扫码登录且在线，7/7 个插件实际加载成功。
修复了跨插件工具导入提前注册 as812 事件的问题，回归测试在 Windows 和树莓派通过。
旧 NapCat 4.9.81 与当前 QQ 存在 Packet 错误及每 20 秒 WebSocket 断连；
已升级到官方 NapCat 4.18.9，校验发布包摘要并保留配置和 QQ 登录会话。
旧目录完整备份于 `~/bot-backups/napcat-before-v4.18.9-20261008-211652`。
升级后独立 WebSocket 连续 65 秒保持连接，bot 日志无反复重连。
用户已确认「测试as812」文字回复和怪猎图片查询均正常。
两个 systemd 用户服务已启用，`Linger=yes`；bot 重启后仍成功加载 7 个插件，
未再出现事件绑定异常或 WS 重连。Steam 经本机代理查询成功。
B 站适配器仍有样例视频评论初次拉取失败、重复动态源跳过的警告，需使用评论监控时
核对原有 B 站数据源配置。小智桥接按用户要求暂时不用。
最终确认 `NTPSynchronized=yes`。已实际执行第 4 节的上传、备份、解压、
离线依赖检查、重启流程；更新后 QQ 在线、7/7 插件加载，服务无自动重启。
本次更新前备份为 `~/bot-backups/bot-20261008-212951.tar.gz`。
