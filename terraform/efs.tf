# Production EFS
resource "aws_efs_file_system" "prod" {
  creation_token   = "tda-efs-prod"
  performance_mode = "generalPurpose"
  throughput_mode  = "bursting"
  encrypted        = true

  tags = { Name = "tda-efs-prod", Env = "prod" }
}

resource "aws_efs_mount_target" "prod" {
  count           = 2
  file_system_id  = aws_efs_file_system.prod.id
  subnet_id       = aws_subnet.private[count.index].id
  security_groups = [aws_security_group.efs.id]
}

# Staging EFS
resource "aws_efs_file_system" "staging" {
  creation_token   = "tda-efs-staging"
  performance_mode = "generalPurpose"
  throughput_mode  = "bursting"
  encrypted        = true

  tags = { Name = "tda-efs-staging", Env = "staging" }
}

resource "aws_efs_mount_target" "staging" {
  count           = 2
  file_system_id  = aws_efs_file_system.staging.id
  subnet_id       = aws_subnet.private[count.index].id
  security_groups = [aws_security_group.efs.id]
}
