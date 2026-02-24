# MiaoMiaoTrader

基于 LLM 的交易机器人，包含规划器、解释器、OKX 适配器、监控与 Web 管理器。

## 安装

```bash
pip install -r requirements.txt
```

## 启动

```bash
python start.py
```

启动后 Web 管理器会打印访问 Token，使用该 Token 登录管理页面。

默认端口可在 `config/app.json` 的 `web_port` 配置项中修改。

## 配置

配置文件位于 `config/` 目录：

- `config/llm.json`：LLM 列表，前面的优先
- `config/okx.json`：OKX 账号与 WebSocket 选项、实盘/模拟盘
- `config/app.json`：交易偏好、任务目标、循环间隔、Web 端口

修改配置后，在 Web 管理器中点击“重启服务”生效。

## Linux 部署（systemd）

创建服务文件：

```
sudo tee /etc/systemd/system/miaomiao-trader.service <<'EOF'
[Unit]
Description=MiaoMiaoTrader
After=network.target

[Service]
Type=simple
WorkingDirectory=/path/to/MiaoMiaoTrader
ExecStart=/usr/bin/python3 /path/to/MiaoMiaoTrader/start.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
```

启用与启动：

```
sudo systemctl daemon-reload
sudo systemctl enable miaomiao-trader
sudo systemctl start miaomiao-trader
```

停止服务：
```
sudo systemctl stop miaomiao-trader
```

查看日志：

```
journalctl -u miaomiao-trader -f
```

## 日志

日志默认输出到：

- `logs/app.log`
- `logs/snapshots/`（异常快照）
