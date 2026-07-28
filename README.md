# 🦞 GitHub Trending Desktop

> 每天早上 9 点自动推送 GitHub 排行榜 Top 5 · 项目搜索 · 一键下载管理

跨平台桌面应用（macOS / Windows / Linux），通过本地 Web GUI 提供 GitHub Trending 浏览、项目搜索、README 渲染、一键下载管理功能。

---

## ✨ 功能

| 功能 | 说明 |
|------|------|
| 🔥 **每日排行** | 自动抓取 GitHub Trending 日榜 Top 5，含 Star 数、语言、License、Topics |
| 🔍 **项目搜索** | 调用 GitHub Search API，支持 `language:xxx`、`stars:>1000`、`topic:xxx` 等高级语法 |
| 📖 **README 渲染** | 展开项目卡片即可查看完整 README（markdown 渲染，支持图片/代码块/表格） |
| ⬇ **一键下载** | 点击下载 → git clone 到本地 → 进度条实时反馈 → 本地包管理 |
| 🕐 **新鲜度指示** | 状态栏实时显示 "🟢 5 分钟前 / 🟡 2 小时前 / 🔴 8 小时前" |
| 🔌 **代理自适应** | 启动时自动探测可用代理（西部世界 VPN / Clash / 直连），故障自动切换 |
| ⏰ **定时更新** | OpenClaw Cron 每天 9:00 AM 自动抓取最新数据 |
| 🌍 **跨平台** | macOS / Windows / Linux 均可运行 |

---

## 🚀 快速开始

### 前置条件

- Python 3.9+
- Git
- VPN / 代理（中国大陆用户访问 GitHub 需要）

### 安装

```bash
git clone https://github.com/KIRRAWA/gh-trending.git
cd gh-trending
```

### 启动

```bash
# 方式一：跨平台启动器（推荐）
python3 launcher.py

# 方式二：直接启动服务器
python3 server.py
```

浏览器自动打开 `http://localhost:19999`。

### 各平台快捷启动

| 平台 | 方式 |
|------|------|
| **macOS** | 双击 `~/Desktop/GitHub Trending.command` |
| **Windows** | 双击 `launcher.bat` |
| **Linux** | 双击 `launcher.sh` |

---

## 📖 使用指南

### 🔥 今日排行

打开页面默认显示当日 GitHub Trending Top 5。点击任意项目卡片展开 README，点击 **⬇ 下载** 克隆项目到本地。

点击右上角 **🔄 从 GitHub 实时获取** 强制刷新数据。

### 🔍 搜索项目

切换到「搜索项目」标签，输入关键词搜索：

| 搜索示例 | 效果 |
|----------|------|
| `web framework` | 搜索名字/描述中包含这些词的项目 |
| `language:rust cli` | 限定 Rust 语言 |
| `topic:react` | 按 React topic 搜索 |
| `stars:>10000 chat` | 万星以上的聊天项目 |
| `language:go stars:>1000 proxy` | 组合条件 |

支持按 ⭐ Star 数 / 🕐 最近更新 / 🔀 Fork 数排序，结果分页浏览。

### 📦 已下载

查看和管理所有已下载到本地的仓库，可以一键在 Finder 中打开或删除。

---

## 🔧 配置

### GitHub Token（可选，推荐）

未认证 API 限制 60 次/小时，设置 Token 后提升至 5000 次/小时：

```bash
export GITHUB_TOKEN="ghp_xxxxxxxxxxxx"
```

去 [GitHub Settings → Tokens](https://github.com/settings/tokens) 生成，无需勾选任何权限（访问公开仓库即可）。

### 代理

`network.py` 启动时自动探测以下代理：

1. 西部世界 VPN Privoxy → `127.0.0.1:10887`
2. 西部世界 VPN Trojan SOCKS5 → `127.0.0.1:10886`
3. Clash HTTP → `127.0.0.1:7890`
4. 直连（备选）

探测结果缓存到 `data/proxy_config.json`，故障时自动重新探测。

### 开机自启

| 平台 | 方法 |
|------|------|
| **macOS** | 系统偏好设置 → 通用 → 登录项 → 添加 `GitHub Trending.app` |
| **Windows** | 创建 `launcher.bat` 快捷方式 → 放入 `shell:startup` 文件夹 |
| **Linux** | 复制 `launcher.desktop` 到 `~/.config/autostart/` |

### 定时抓取（OpenClaw Cron）

项目内置了 OpenClaw Cron 任务，每天 9:00 AM 自动抓取：

```bash
openclaw cron add \
  --name "gh-trending-daily" \
  --cron "0 9 * * *" \
  --tz "Asia/Shanghai" \
  --message "cd /path/to/gh-trending && python3 fetch_trending.py --save --top 5" \
  --session isolated \
  --timeout-seconds 120
```

---

## 🏗️ 架构

```
┌──────────────────────────────────────────────┐
│                   OpenClaw Cron              │
│                 每天 9:00 AM 触发              │
│                      │                       │
│              fetch_trending.py               │
│              ├─ GitHub Trending 页面抓取       │
│              ├─ GitHub API 元数据补充          │
│              └─ 写入 data/trending.json       │
│                      │                       │
│              ┌───────┴───────┐               │
│              │  server.py    │               │
│              │  localhost:19999              │
│              ├───────────────┤               │
│              │  REST API     │               │
│              │  /api/trending│               │
│              │  /api/search  │               │
│              │  /api/readme  │               │
│              │  /api/download│               │
│              ├───────────────┤               │
│              │  static/      │               │
│              │  index.html   │               │
│              └───────────────┘               │
│                      │                       │
│              浏览器 GUI                       │
│         http://localhost:19999               │
└──────────────────────────────────────────────┘
```

---

## 📁 项目结构

```
gh-trending/
├── README.md           # 本文件
├── network.py          # 代理自适应层 (4路探测 + 缓存)
├── fetch_trending.py   # 数据抓取 (Trending + API)
├── server.py           # HTTP 服务器 + REST API
├── launcher.py         # 跨平台启动器
├── launcher.bat        # Windows 双击启动
├── launcher.sh         # Linux 双击启动
├── static/
│   └── index.html      # Web GUI (亮色主题)
├── data/               # 运行时数据 (JSON)
├── repos/              # 已下载的仓库
└── .claude/            # Claude Code 权限配置
```

---

## 📄 License

MIT
