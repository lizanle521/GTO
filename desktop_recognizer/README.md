# 桌面识别 Desktop Recognizer

截图桌面上任意软件界面，交给多模态 AI 大模型识别并描述内容。

## 快速开始

1. 双击 **`启动.bat`** 运行程序
2. 首次使用需点击工具栏 **「设置」**，选择服务商预设并填入 **API Key**
3. 点击 **「截取屏幕」** 或 **「框选区域」** 截图
4. 点击 **「开始识别」**（或按 F5）查看结果

## 快捷键

| 快捷键 | 功能 |
|---|---|
| `Ctrl + N` | 截取屏幕 |
| `Ctrl + R` | 框选区域 |
| `F5` | 开始识别 |
| `Ctrl + ,` | 打开设置 |
| `Esc` | 取消区域选择 |

## 支持的服务商

软件使用 **OpenAI 兼容接口**，内置以下预设，选择后只需填 API Key：

| 服务商 | 模型 | 获取 Key |
|---|---|---|
| OpenAI | gpt-4o-mini | platform.openai.com |
| 阿里云通义千问 | qwen-vl-max | 阿里云百炼控制台 |
| 智谱 GLM | glm-4v-flash（免费） | open.bigmodel.cn |
| Kimi (Moonshot) | moonshot-v1-8k-vision-preview | platform.moonshot.cn |
| DeepSeek | deepseek-chat | platform.deepseek.com |
| 本地 Ollama | llama3.2-vision | 需本地安装 Ollama，免 Key |

也可选「自定义」，手动填写任意兼容端点的地址与模型名。

> **推荐**：想免费试手，可用智谱 `glm-4v-flash`；想效果最好，用通义千问 `qwen-vl-max` 或 OpenAI `gpt-4o-mini`。

## 功能说明

- **多显示器支持**：可截取全部显示器拼合画面，或指定单个显示器
- **区域框选**：全屏遮罩下拖拽框选任意区域，精确识别某个窗口或按钮
- **自动保存截图**：默认将截图保存到 `图片/DesktopRecognizer` 目录（可在设置中关闭或改路径）
- **结果可编辑**：识别结果支持手动修改、一键复制、保存为 txt
- **用量统计**：状态栏显示本次请求消耗的 token 数

## 文件结构

```
desktop_recognizer/
├── main.py          主界面与交互逻辑（PyQt6）
├── capture.py       屏幕截图与图像编码
├── recognizer.py    AI 模型调用与错误处理
├── config.py        配置读写
├── 启动.bat         一键启动
├── install.bat      依赖安装
└── README.md        本文件
```

## 常见问题

**Q：提示"未配置 API Key"？**
打开设置填入 Key。若用本地 Ollama 等本地服务，地址含 `localhost` 可免 Key。

**Q：识别很慢或超时？**
软件会自动把截图缩放到宽 1920px 以内。若仍慢，可在设置中降低「最大输出长度」，或换用更快的模型（如 glm-4v-flash）。

**Q：中文识别不准？**
在设置中把提示词改得更具体，例如「请逐字提取界面中的所有中文文字，并按区域分组列出」。

**Q：截图是黑的？**
某些受保护窗口（如部分视频播放器）无法截取，属系统限制。

## 配置文件位置

`C:\Users\<用户名>\.desktop_recognizer\config.json`

API Key 以明文存储在该文件中，请注意保管，不要分享此文件。
