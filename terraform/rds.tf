resource "aws_db_subnet_group" "main" {
  name       = "tda-db-subnet-group"
  subnet_ids = aws_subnet.private[*].id
  tags       = { Name = "tda-db-subnet-group" }
}

# Production RDS - Multi-AZ MariaDB
resource "aws_db_instance" "prod" {
  identifier              = "tda-rds-prod"
  engine                  = "mariadb"
  engine_version          = "10.11"
  instance_class          = var.rds_instance_class
  allocated_storage       = 20
  max_allocated_storage   = 100
  storage_encrypted       = true
  db_name                 = var.db_name
  username                = var.db_username
  password                = var.db_password
  db_subnet_group_name    = aws_db_subnet_group.main.name
  vpc_security_group_ids  = [aws_security_group.rds.id]
  multi_az                = true
  backup_retention_period = 30
  deletion_protection     = true
  skip_final_snapshot     = false
  final_snapshot_identifier = "tda-rds-prod-final"

  tags = { Name = "tda-rds-prod", Env = "prod" }
}

# Staging RDS - single AZ MariaDB
resource "aws_db_instance" "staging" {
  identifier              = "tda-rds-staging"
  engine                  = "mariadb"
  engine_version          = "10.11"
  instance_class          = "db.t3.small"
  allocated_storage       = 20
  storage_encrypted       = true
  db_name                 = var.db_name
  username                = var.db_username
  password                = var.db_password
  db_subnet_group_name    = aws_db_subnet_group.main.name
  vpc_security_group_ids  = [aws_security_group.rds.id]
  multi_az                = false
  backup_retention_period = 7
  deletion_protection     = false
  skip_final_snapshot     = true

  tags = { Name = "tda-rds-staging", Env = "staging" }
}
