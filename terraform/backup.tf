resource "aws_iam_role" "backup" {
  name = "tda-backup-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "backup.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "backup" {
  role       = aws_iam_role.backup.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSBackupServiceRolePolicyForBackup"
}

resource "aws_backup_vault" "main" {
  name = "tda-backup-vault"
  tags = { Name = "tda-backup-vault" }
}

resource "aws_backup_plan" "main" {
  name = "tda-backup-plan"

  rule {
    rule_name         = "daily-30-day-retention"
    target_vault_name = aws_backup_vault.main.name
    schedule          = "cron(0 2 * * ? *)"

    lifecycle {
      delete_after = 30
    }
  }

  tags = { Name = "tda-backup-plan" }
}

resource "aws_backup_selection" "efs_prod" {
  name         = "tda-efs-prod-backup"
  plan_id      = aws_backup_plan.main.id
  iam_role_arn = aws_iam_role.backup.arn

  resources = [aws_efs_file_system.prod.arn]
}
