# status-panel — 本地舰队可观测面板

- 面板：**http://127.0.0.1:8766/**（`PANEL_PORT` 改端口；stdlib-only、只读）
- 启动：`setsid nohup python3 bench/py/status_panel.py >> bench/results/status-panel/run.log 2>&1 </dev/null &`
- 停止：`kill "$(cat bench/results/status-panel/panel.pid)"`
- 日志：`bench/results/status-panel/run.log`；pidfile 同目录

## 任务上报约定（任意 agent / 脚本可用）

看板数据源 = `tasks.d/*.json`。不要手写 JSON，用工具：

```bash
python3 bench/py/task_ping.py <任务名> --status running --done 40 --total 200 --note "xlat 臂" --owner <会话名>
python3 bench/py/task_ping.py <任务名> --finish            # 完结
python3 bench/py/task_ping.py <任务名> --status blocked --note "等网关"
python3 bench/py/task_ping.py <任务名> --remove            # 撤下看板
python3 bench/py/task_ping.py --list                       # CLI 侧查看
```

status ∈ `starting|running|blocked|done|failed`。running/blocked 超过 15 分钟未上报会被面板标「静默」。长跑任务建议每完成一小批就 ping 一次（开销一次原子写文件）。owner 默认取 `$TEXLATE_AGENT` 或系统用户名。
