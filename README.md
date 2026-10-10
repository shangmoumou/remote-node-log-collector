# Remote Node Log Collector

远程节点日志采集工具：通过 SFTP 按时间提取各节点 INFO、WARNING 和 ERROR 日志，支持 Xftp 会话导入和 Windows EXE 打包。

双击 `start.cmd` 启动。首次运行自动安装 SFTP 依赖，需要联网。

启动窗口显示四个阶段和依赖下载进度；详细日志保存在工具目录 `logs` 下。安装设有网络超时，失败后窗口保留错误和日志路径。阶段编号不代表下载百分比，实际下载进度由 pip 显示。依赖安装到工具目录 `.dependencies`。

## 分发给别人

- 脚本方式：复制工具目录，目标电脑需安装 Python 3.10 或更新版本（包含 tkinter），双击 `start.cmd`。首次安装需要联网。
- EXE 方式：在有 Python 的 Windows 电脑上双击 `build_exe.cmd`，自动安装打包依赖并生成 `dist/LogDownloader.exe`。把 EXE 放入可写文件夹分发，目标电脑无需 Python，也无需安装依赖。首次打包需要联网。请在目标 Windows 系统上验证运行。
- EXE 的机器配置和主机密钥保存在 EXE 旁边。分发时只发送 EXE，不要附带自己的 `machines.json`、`known_hosts` 或安装日志。Xftp 会话从使用者自己的文档目录读取。

选择 Xftp 会话，填写密码，或填写新机器信息并保存。勾选“保存密码（本机加密）”后点击“保存机器”，以后选择该机器会自动恢复密码；取消勾选再保存会清除配置中的密码。Xftp 加密密码无法直接复用。

默认选择“最新日志”；选择“指定时间”后，通过年、月、日、时、分、秒控件设置时间，默认值为当前本地时间。指定时间时，从每个节点的 `_info_YYYYMMDD-HHMMSS.*` 中选择启动时间不晚于输入时间的最新文件。所选时间应使用远程日志命名所使用的时区。此规则基于文件启动时间区间，不检查日志正文；已清理的历史日志无法恢复。

选择“最新日志”时，下载每个节点目录中所有以 `.INFO`、`.WARNING`、`.ERROR` 结尾的文件，无需与目录同名，例如 `dynamic_controller/dcn.INFO`。

指定时间时，INFO、WARNING、ERROR 三个级别分别按文件名时间选择最近的一份；文件名中的 `warn`、`warning`、`error` 和 `.WARNING`、`.ERROR` 都会识别。没有某个级别日志时自动跳过。

保存机器时，密码使用当前 Windows 用户的 DPAPI 加密后保存，只有同一 Windows 用户可以解密使用；Xftp 导入会话本身不会读取 Xftp 的密码。

每次在 Windows 桌面新建一个目录，所有日志使用原名称放在同一目录；`提取结果.txt` 记录成功和失败。同名文件会跳过并记录，避免覆盖其他节点的日志。未完成的下载使用 `.part` 后缀。

首次连接需核对主机密钥指纹。后续主机密钥变化会拒绝连接。

无需编译任何 ROS 节点。运行依赖为 Python（含 tkinter）及 requirements.txt 中的 Paramiko。
