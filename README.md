# 六宫格参考图+画风完整版本1023

保存用户验证正确的 **2026-10-23 15:43:00** 历史源码基线。

应用程序源码、原强参考图 Prompt、参考图上传流程及静态资源按该备份保存，未改写生图逻辑。各文件校验值见 `SOURCE_MANIFEST.json`，原版使用文档保存在 [docs/README.1023-original.md](docs/README.1023-original.md)。

## 运行

使用带 Tkinter 的 Windows Python 环境，在项目目录执行：

```powershell
python -m pip install -r requirements.txt
python launch_gui.py
```

也可双击 `launch_gui.cmd`。首次启动会在本地建立 SQLite 数据库。账号、标题、参考图和 API 配置由使用者在本地导入与设置；此仓库保存程序源码和静态资源，不包含个人数据库、密钥或生成作品。

## 版本范围

- 参考图生图、画风生图、六宫格参考图生图、参考图连续生图、六宫格画风生图。
- 使用该版本原有的强参考 Prompt 和文案分配流程。
- 不含后来新增的形象生图、语义编排及其他后续功能。

## 打包

`PicFactoryGUI.spec` 保留原版打包配置。其中 `TK_PYTHON` 是原构建机的 Tk 运行库目录，在其他机器打包时需按本机环境设置；配置还会读取本地初始化后的 `picfactory_matrix.db`。

```powershell
python -m PyInstaller --noconfirm --clean PicFactoryGUI.spec
```

版本备注：**六宫格参考图+画风完整版本1023**。
