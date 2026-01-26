# AWS Budgets & Cost Monitoring

OpenTofu project for managing AWS cost budgets, anomaly detection, and free tier alerts.

## Features

- **Monthly budgets** with email alerts at 80% and 100%
- **Cost anomaly detection** with automatic email notifications
- **Free tier usage tracking** (coming soon)

## Deployment

```bash
cd tofu/budgets/environments/prod
tofu init
tofu plan
tofu apply
```

## Configuration

Budget settings are configured in `environments/prod/main.tf`:
- **Monthly limit**: $10 USD
- **Alert thresholds**: 80% and 100%
- **Notification email**: dave@repeatersolutions.com

## Resources Managed

- `aws_budgets_budget` - Monthly spending limit with notifications
- `aws_ce_anomaly_monitor` - Detects unusual spending patterns
- `aws_ce_anomaly_subscription` - Email alerts for anomalies
