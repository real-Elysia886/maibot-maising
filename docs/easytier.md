# 使用 EasyTier 跨机器连接

适用于 MaiBot 在云服务器、GPU 推理服务在家用电脑的情况。同一台机器且同一网络命名空间时不需要 EasyTier；先阅读[部署指南](deployment.md)。

以下虚拟 IP 仅为示例：云端 `10.42.0.1`，GPU 电脑 `10.42.0.2`。选择与两端现有局域网、VPN、Docker 网段不冲突的虚拟网段。EasyTier 和推理服务分别使用自己的密钥，不要复用。

## 1. 两端加入同一网络

在两台机器分别安装 [EasyTier 官方发行版](https://github.com/EasyTier/EasyTier/releases)。Windows 可以使用 GUI；Linux 可使用命令行。创建相同的网络名称和强随机网络密钥，给两端分配不同虚拟 IPv4。按官方指导选择公共节点或自建节点，确认两端通过同一组节点加入网络。

使用公共节点的具体步骤见[官方无公网 IP 组网教程](https://doc.easytier.cn/guide/network/networking-without-public-ip.html)。命令行的 `--network-secret` 可能被本机进程列表或命令历史看到；正式使用建议通过 EasyTier GUI 或权限受限的配置文件保存密钥。不要把真实网络密钥和 IP 写入本项目或发到公开场合。

如果使用命令行，可在两台机器分别新建 EasyTier 自己的配置文件（不要放入本插件仓库）：

```toml
ipv4 = "10.42.0.1"

[network_identity]
network_name = "替换为你自己设置的网络名称"
network_secret = "替换为你自己生成的网络密钥"

[[peer]]
uri = "tcp://public.easytier.top:11010"
```

上面是云端示例，GPU 电脑使用相同的名称、密钥和节点，但将 `ipv4` 改成 `10.42.0.2`。两端在 EasyTier 程序目录分别启动：Windows 管理员 PowerShell 执行 `.\easytier-core.exe -c .\easytier-config.toml`；Linux 执行 `sudo ./easytier-core -c /实际路径/easytier-config.toml`。文件名可自行指定；Linux 可先用 `chmod 600 /实际路径/easytier-config.toml` 限制读取权限，Windows 也应只让信任的账户读取该文件。

以上示例供手动了解流程；已经部署了 EasyTier 的用户，直接使用现有网络和实际虚拟 IP，不要重复启动或覆盖原配置。虚拟网卡、管理员权限、开机自启与版本相关设置请参照官方文档。

启动后在各自机器使用 `easytier-cli peer` 查看节点，再从 MaiBot 所在机器尝试访问 GPU 机器的虚拟 IP。是否直连取决于网络环境，也可能使用中继；不能保证延迟或零流量费用。

## 2. 配置 GPU 端推理服务

在 GPU 机器的 `server/settings.json` 中设置，模型路径按实际情况修改：

```json
{
  "host": "10.42.0.2",
  "port": 9881,
  "api_token": "替换为你自己生成的长随机令牌",
  "rvc_model": "models/elysiav3.pth",
  "rvc_index": "",
  "uvr_model": "models/HP5_only_main_vocal.pth",
  "uvr_tools_dir": "填写包含 vr.py 的目录"
}
```

将 `host` 换成 GPU 机器自己的 EasyTier 虚拟 IP。如果虚拟网卡尚未就绪，先启动 EasyTier。也可以使用 `0.0.0.0`，但它会监听所有网卡，必须用防火墙限制 9881 的来源；非本机监听时服务要求配置 `api_token`。`settings.json` 包含令牌，已被 `.gitignore` 忽略，不要分享或提交。修改后重启推理服务。

例如可在本机运行 `python -c "import secrets; print(secrets.token_urlsafe(32))"` 生成服务令牌，把输出分别填到服务端和 WebUI；不要把输出放进示例文件或公开聊天。

## 3. 配置 MaiBot 插件

在 MaiBot WebUI 中设置「唱歌服务地址」为 GPU 机器的地址，例如 `http://10.42.0.2:9881`，并在「唱歌服务令牌」中填写与 `api_token` 相同的值，**不是 EasyTier 的网络密钥**。

如果 MaiBot 在 Docker 中运行，`127.0.0.1` 指容器自身。要从容器内部验证到 GPU 虚拟 IP 的路由和 9881 连通性；处理方式取决于 Docker 网络、宿主路由和防火墙。语音适配器在另一个容器时，还需与 MaiBot 共享插件的音频临时目录。

## 4. 排查

- 节点不互见：核对网络名称、密钥、虚拟 IP、公共节点、防火墙及网络状态，参考官方日志和文档。
- 节点互通但连接服务失败：确认 GPU 端监听地址、9881 防火墙规则和容器内路由。
- 返回 401：检查服务端与 WebUI 的令牌是否一致；不要公开粘贴令牌。
- 服务正常但不能发送语音：检查适配器是否支持 `voiceurl`，以及是否可访问共享文件路径。

EasyTier 的访问权限取决于网络成员及其配置。插件与服务之间使用 HTTP，服务令牌本身不提供传输加密；应使用可信的加密组网，并限制网络和防火墙访问。
