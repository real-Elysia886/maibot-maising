# Fairseq 预编译包说明

唱歌服务使用 `rvc-python==0.1.5`，它依赖 `fairseq==0.12.2`。为了减少 Windows 用户编译负担，`v1.2.0` Release 计划提供 `fairseq-0.12.2-cp39-cp39-win_amd64.whl`，适用于 64 位 Windows 和 CPython 3.9。

- 上游项目：[facebookresearch/fairseq](https://github.com/facebookresearch/fairseq)，MIT 许可证；wheel 内保留上游许可证。
- 上游源码：PyPI 的 [fairseq 0.12.2 源码包](https://pypi.org/project/fairseq/0.12.2/#files)，SHA-256 `34f1b18426bf3844714534162f065ab733e049597476daa35fffb4d06a92b524`。
- wheel SHA-256：`6462b57088ba3d070016b5c58660233816bdbfe149747c9586b579a1e2355ea1`。
- 构建环境：Windows x64、Python 3.9.23、pip 23.3.2、Microsoft C++ 工具；从 PyPI 源码包在本项目隔离验证环境中构建。该包不是 Fairseq 官方提供的 Windows wheel。
- 安装器固定下载地址与 SHA-256，下载或校验失败时停止，不会自动使用未知来源的软件包。

该 wheel 已通过隔离环境的无源码构建安装、RVC 模块导入检查；完整音频生成是在安装后进行过验证的同类隔离环境中完成。它尚未在另一台无 C++ 工具的全新 Windows 机器上完成端到端验证；如需要自行编译，可参考上游文档和 Microsoft C++ Build Tools。
