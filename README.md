# 🎬 儿童视频播放器

一个专为儿童设计的视频播放应用，支持B站视频下载和本地播放。

## ✨ 功能特点

- 📁 **文件夹浏览**: 像文件管理器一样浏览视频文件夹
- 🎬 **B站视频支持**: 解析B站链接，按需下载视频
- 📱 **儿童友好界面**: 大按钮、清晰图标、简洁明了
- ⬇️ **智能下载**: 只在播放时下载，节省存储空间
- 🎯 **进度跟踪**: 实时显示下载进度
- 📺 **本地播放**: 支持多种视频格式播放
- 🌐 **Web应用**: 可在浏览器使用，也可打包成安卓APP

## 🚀 快速开始

### 1. 环境要求

- Python 3.8+
- FFmpeg (用于视频合并)

### 2. 安装依赖

```bash
pip install -r backend/requirements.txt
```

### 3. 启动应用

```bash
python start_app.py
```

应用会自动在浏览器中打开: http://localhost:8000

### 4. 添加视频

在 `videos/文件夹名/list.txt` 中添加B站视频链接：

```
# 动画片视频列表
https://www.bilibili.com/video/BV1xx411c7mu
https://www.bilibili.com/video/BV1GJ411x7h7
```

## 📁 项目结构

```
player/
├── backend/                 # 后端API服务
│   ├── main.py             # 主应用入口
│   ├── bilibili_downloader.py  # B站下载器
│   ├── models.py           # 数据模型
│   ├── requirements.txt    # Python依赖
│   └── start_server.py     # 启动脚本
├── frontend/               # Web前端应用
│   ├── index.html          # 主页面
│   ├── styles.css          # 样式文件
│   ├── app.js              # 应用逻辑
│   ├── manifest.json       # PWA配置
│   └── sw.js               # Service Worker
├── videos/                 # 视频存储目录
│   ├── 动画片/
│   │   └── list.txt        # B站链接列表
│   └── 教育视频/
├── run.py                  # 一键启动脚本
└── 1.py                    # 原始B站下载脚本
```

## 🔧 技术架构

### 后端 (Python + FastAPI)
- **FastAPI**: 现代化的异步API框架
- **异步下载**: 支持并发下载和进度回调
- **B站视频解析**: 基于原有1.py的逻辑重构

### 前端 (HTML/CSS/JavaScript)
- **响应式设计**: 适配手机和电脑
- **PWA支持**: 可添加到手机桌面
- **儿童友好UI**: 大按钮、明亮色彩

## 📱 打包成安卓APP

### 方法1: 使用Cordova

```bash
# 安装Cordova
npm install -g cordova

# 创建项目
cordova create myapp com.example.kidsplayer "儿童视频播放器"

# 复制前端文件到www目录
cp -r frontend/* myapp/www/

# 添加Android平台
cd myapp
cordova platform add android

# 构建APK
cordova build android
```

### 方法2: PWA方式

1. 在手机浏览器打开应用
2. 点击"添加到主屏幕"
3. 即可像原生APP一样使用

## 🎯 使用说明

### 添加视频内容

1. 在`videos`目录下创建文件夹（如"动画片"、"教育视频"）
2. 在文件夹内创建`list.txt`文件
3. 每行添加一个B站视频链接
4. 支持以`#`开头的注释行

### 观看视频

1. 打开应用，选择文件夹
2. 点击想看的视频
3. 首次播放会自动下载
4. 下载完成后自动播放

## 🛠️ 开发说明

### API接口

- `GET /folders` - 获取文件夹列表
- `GET /videos/{folder_path}` - 获取视频列表
- `POST /download` - 开始下载视频
- `GET /download/status/{task_id}` - 查询下载状态
- `GET /stream/{folder_path}/{filename}` - 视频流

### 自定义配置

- 修改`frontend/styles.css`自定义界面样式
- 修改`backend/bilibili_downloader.py`添加新的视频源
- 修改`frontend/manifest.json`配置PWA属性

## ❓ 故障排除

### 常见问题

1. **FFmpeg未找到**
   - 下载安装FFmpeg: https://ffmpeg.org/download.html
   - 确保ffmpeg在系统PATH中

2. **视频下载失败**
   - 检查B站链接是否有效
   - 确认网络连接稳定

3. **无法访问应用**
   - 检查防火墙设置
   - 确认后端服务正在运行

## 📄 许可证

MIT License

## 🤝 贡献

欢迎提交Issue和Pull Request！