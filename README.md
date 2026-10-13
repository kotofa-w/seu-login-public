# 东南大学校园网自动登录

面向 Windows 的 SEU-WLAN / SEU-ISP 认证工具，提供 Tkinter 界面、命令行、连接事件触发和可选周期检查。当前版本为 **1.1.0**。

程序在已经连接校园 Wi-Fi 后检查认证状态，未认证时提交登录；不会选择或切换 Wi-Fi，也不会修改网卡、DNS、路由或系统代理。

## 快速开始

需要 Windows 10/11、Python 3.10 或更新版本，以及 Python 自带的 Tkinter。请确保 `python` 和 `pythonw` 可从命令行调用。

在 CMD 中运行：

```cmd
git clone https://github.com/kotofa-w/seu-login-public.git "%USERPROFILE%\Documents\seu-login-public"
cd /d "%USERPROFILE%\Documents\seu-login-public"
python -m pip install requests
setup.bat
start_gui.bat
```

没有 Git 时，可选择 **Code → Download ZIP**，解压后进入目录，执行后三步。

配置向导会询问账号、密码和运营商，也会询问是否立即测试登录。使用 SEU-ISP 时选择实际运营商；自动识别模式下，连接 SEU-WLAN 会自动使用统一身份认证，无需改运营商选择。

仓库只附带空的 `seu_login.example.ini`。向导或界面保存后会创建本机 `seu_login.ini`。界面“立即登录”用于手动认证。

## 选择自动执行方式

| 方式 | 何时检查 | 关闭界面后 | 适合场景 |
| --- | --- | --- | --- |
| 守护模式 | 打开界面约一秒后，随后默认每 30 秒 | 界面监测停止 | Wi-Fi 没断开但认证会过期 |
| 连接触发模式 | Wi-Fi 连接事件后延迟 5 秒；Windows 登录后延迟 30 秒 | 已安装的任务继续有效 | 只在连接时检查 |
| 单次开机任务 | Windows 用户登录后延迟 30 秒 | 登录后程序退出 | 只需开机认证一次 |

在 **其他设置 → 连接监测维护模式** 中选择守护或连接触发，然后点击 **保存所有设置**。两种选择互斥，也可都关闭。事件任务的安装或移除只在保存时执行，直接关闭界面不会安装任务。

程序先查询门户状态：已认证则跳过，明确未认证才登录；状态查询失败时等待下一次检查。自动检测只接受 SEU-WLAN / SEU-ISP，其他网络不会自动认证。

### 连接触发模式

安装需要管理员权限和已开启的 `Microsoft-Windows-WLAN-AutoConfig/Operational` 日志。推荐右键 `start_gui.bat`，选择 **以管理员身份运行**，再选择连接触发模式并保存。

也可在管理员 CMD 中安装：

```cmd
powershell -NoProfile -ExecutionPolicy Bypass -File "%USERPROFILE%\Documents\seu-login-public\install-network-trigger.ps1" -ConfigPath "%USERPROFILE%\Documents\seu-login-public\seu_login.ini"
```

安装器创建独立任务 `SEU_NetworkConnect`，不会立刻执行认证。每次触发最多检查三次，失败间隔五秒；单次触发内每次最多尝试一次认证，结束后退出。任务最长运行五分钟，已运行时忽略重复触发。

同名任务属于其他程序或配置路径不同，安装器会停止而非覆盖。安装后不要移动脚本或配置。卸载：

```cmd
powershell -NoProfile -ExecutionPolicy Bypass -File "%USERPROFILE%\Documents\seu-login-public\install-network-trigger.ps1" -Remove
```

事件模式不会覆盖“Wi-Fi 未重新连接但认证已过期”，需要覆盖这种情况时选择守护模式。安装或自检通过不能替代真实事件验证。

### 单次任务与命令行守护

```cmd
cd /d "%USERPROFILE%\Documents\seu-login-public"
python seu_login.py --install-start
python seu_login.py --remove-start
pythonw seu_login.py --daemon
```

`--install-start` 管理 `SEU_AutoLogin` 单次任务，同名原任务可能被覆盖，且可能需要管理员权限。它与 `SEU_NetworkConnect` 是两个任务；避免同时保留重复的开机认证入口。

`--daemon` 是独立常驻进程，不是安装后台服务。使用前需在设置中开启守护模式；不要同时运行多个守护进程，或与连接事件模式叠加。

开启守护时，手动注销后可能在下一轮被重新认证。需要保持注销状态时先关闭守护；连接触发模式则在下次连接事件发生时检查。

## 网络与账号

| 网络 | 认证方式 |
| --- | --- |
| SEU-WLAN | 统一身份认证，账号格式为 `,1,账号`，无运营商后缀 |
| SEU-ISP | 按配置选择联通、电信或移动，保留运营商认证格式 |

运营商配置值：`unicom`、`telecom`、`mobile`；`campus` 表示校园认证。两种网络目前共用一组凭据。如果你的凭据不同，需要手动切换配置，本程序不自动管理两套凭据。

其他命令：

```cmd
cd /d "%USERPROFILE%\Documents\seu-login-public"
python seu_login.py --status
python seu_login.py --logout
python seu_login.py --on-network-connect
python seu_login.py --manual-network --isp campus
python seu_login.py --manual-network --isp unicom
```

`--on-network-connect` 会实际检查并可能认证，仅在需要手动验证事件入口时执行。关闭自动 SSID 检测可在界面取消“自动识别”，或使用 `--manual-network`。

## 隐私和边界

- 仓库为独立脱敏源码快照，不携带私人 Git 历史、真实配置、日志、截图、备份或会话数据。测试只使用合成凭据和示例地址。
- 本机配置中的密码仍以明文保存。`.gitignore` 排除 INI、日志、环境文件和缓存，仅保留空配置示例。不要提交或分享真实配置，也不要通过命令行 `--password` 暴露密码。
- 认证日志不输出完整账号、客户端 IP、原始认证响应或完整命令行；认证请求异常仅记录类别。任务管理错误可能包含本机路径，分享诊断信息前需检查。
- 认证请求直连校园门户，绕过环境代理，不修改系统代理。现有实现关闭 TLS 证书校验，请仅在可信校园网络使用。
- 保留东南大学固定认证域名和控制器地址。WLAN 使用 HTTPS 802，ISP 保留原 HTTPS 801。WLAN 优先使用动态控制器参数；官方 Dr.COM 登录页缺参时使用当前已验证的控制器回退值，客户端 IP 从本次页面获取。学校调整认证系统后可能需要更新。
- SSID 查询可能受 Windows 定位权限或管理员权限限制。未知网络、多无线连接产生歧义、用户 IP 缺失时停止自动认证。
- 外网探测返回 `204` 只说明网络可访问，不能单独证明校园网认证完成；VPN、多网卡场景需核对实际连接。

## 离线检查

在 Windows CMD 中执行：

```cmd
cd /d "%USERPROFILE%\Documents\seu-login-public"
mkdir _test_config
python -B privacy_selfcheck.py
python -B event_selfcheck.py
python -B guardian_selfcheck.py
powershell -NoProfile -File "%USERPROFILE%\Documents\seu-login-public\trigger_type_selfcheck.ps1"
rmdir _test_config
```

检查使用模拟响应，或在内存构造任务对象，不提交认证、不安装任务。模拟失败分支的错误输出是预期结果，以最后的 `PASS` 为准。

## 常见问题

**切换 Wi-Fi 后没有自动认证**：确认选择连接触发模式并保存成功，任务计划程序中存在且启用了 `SEU_NetworkConnect`。只替换代码不会安装任务；只开启守护但关闭界面也不会持续检测。

**触发任务设置失败**：用管理员权限保存，确认 WLAN 事件日志已开启及同名任务未冲突。安装器使用完整 CIM 类元数据，注册、启用或删除失败会停止，不误报成功。

**更新后行为没变**：关闭旧界面并重新启动。已经运行的 Python 进程不会自动加载新文件。