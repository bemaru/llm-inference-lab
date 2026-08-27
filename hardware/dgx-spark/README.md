# DGX Spark-Class Hardware

Sanitized notes for DGX Spark-class unified-memory experiments.

Do not include internal hostnames, IP addresses, account names, or company-specific deployment details.

## Dashboard Tunnel

The dashboard listens on the remote loopback interface. Start an SSH tunnel from WSL, then open `http://127.0.0.1:11000` on the operator machine.

```bash
hardware/dgx-spark/dashboard-tunnel.sh start <ssh-target>
```

Inspect or stop the managed tunnel with:

```bash
hardware/dgx-spark/dashboard-tunnel.sh status <ssh-target>
hardware/dgx-spark/dashboard-tunnel.sh stop <ssh-target>
```

The SSH target and credentials remain in the operator's SSH configuration. The repository stores only the reusable tunnel behavior. Override the ports when necessary with `DGX_SPARK_DASHBOARD_LOCAL_PORT` and `DGX_SPARK_DASHBOARD_REMOTE_PORT`.
