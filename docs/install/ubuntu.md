# Ubuntu 环境准备

本页只关注运行这个仓库需要的基础环境，不展开额外的 Linux 调优内容。

## 更新系统包

```bash
sudo apt update
sudo apt upgrade -y
```

## 安装 Python 3 和常用工具

```bash
sudo apt install -y python3 python3-pip python3-venv git curl
```

确认版本：

```bash
python3 --version
pip3 --version
git --version
```

## 安装 Node.js / npm

NapCat 相关环境通常会用到 Node.js / npm，建议先装上：

```bash
sudo apt install -y nodejs npm
```

确认版本：

```bash
node -v
npm -v
```

## 克隆仓库

```bash
git clone <your-repo-url>
cd candace-ai-agent
```

## 创建 Python 虚拟环境（推荐）

```bash
python3 -m venv .venv
source .venv/bin/activate
```

激活后再安装依赖：

```bash
python3 -m pip install -r requirements.txt
```

## 目录权限与本地运行说明

这是一个偏本地长期运行的项目，通常会用到：

- webhook 监听端口
- 本地 JSON 文件读写
- 日志输出到终端

建议直接在你自己的 Ubuntu 用户目录下运行，不要一开始就上复杂的 systemd 或容器化。

先把本地开发链路跑通，再考虑长期托管方式。
