resource "aws_key_pair" "main" {
  key_name   = "tda-key"
  public_key = file("~/.ssh/tda_key.pub")
}

resource "aws_iam_instance_profile" "ec2" {
  name = "tda-ec2-profile"
  role = aws_iam_role.ec2.name
}

resource "aws_iam_role" "ec2" {
  name = "tda-ec2-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy_attachment" "cloudwatch" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}

locals {
  cloud_init_prod = <<-EOF
    #!/bin/bash
    yum update -y
    yum install -y amazon-efs-utils nfs-utils amazon-cloudwatch-agent

    # Mount EFS
    mkdir -p /mnt/efs
    echo "${aws_efs_file_system.prod.id}:/ /mnt/efs efs _netdev,tls 0 0" >> /etc/fstab
    mount -a

    # Create Joomla persistent dirs on EFS
    mkdir -p /mnt/efs/images /mnt/efs/media /mnt/efs/logs /mnt/efs/config

    # Symlink persistent dirs into Joomla webroot
    WEBROOT=/var/www/html/joomla
    mkdir -p $WEBROOT
    ln -sfn /mnt/efs/images  $WEBROOT/images
    ln -sfn /mnt/efs/media   $WEBROOT/media
    ln -sfn /mnt/efs/logs    $WEBROOT/logs

    # Start CloudWatch agent
    /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
      -a fetch-config -m ec2 -s

    # Export DB connection for Joomla
    cat >> /etc/environment <<ENV
    DB_HOST=${aws_db_instance.prod.address}
    DB_NAME=${var.db_name}
    DB_USER=${var.db_username}
    ENV
  EOF

  cloud_init_staging = <<-EOF
    #!/bin/bash
    yum update -y
    yum install -y amazon-efs-utils nfs-utils amazon-cloudwatch-agent

    # Mount EFS
    mkdir -p /mnt/efs
    echo "${aws_efs_file_system.staging.id}:/ /mnt/efs efs _netdev,tls 0 0" >> /etc/fstab
    mount -a

    mkdir -p /mnt/efs/images /mnt/efs/media /mnt/efs/logs /mnt/efs/config

    WEBROOT=/var/www/html/joomla
    mkdir -p $WEBROOT
    ln -sfn /mnt/efs/images  $WEBROOT/images
    ln -sfn /mnt/efs/media   $WEBROOT/media
    ln -sfn /mnt/efs/logs    $WEBROOT/logs

    /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
      -a fetch-config -m ec2 -s

    cat >> /etc/environment <<ENV
    DB_HOST=${aws_db_instance.staging.address}
    DB_NAME=${var.db_name}
    DB_USER=${var.db_username}
    ENV
  EOF
}

# Production Launch Template
resource "aws_launch_template" "prod" {
  name_prefix   = "tda-prod-"
  image_id      = data.aws_ami.cloudlinux.id
  instance_type = var.ec2_instance_type

  key_name = aws_key_pair.main.key_name

  iam_instance_profile {
    name = aws_iam_instance_profile.ec2.name
  }

  network_interfaces {
    associate_public_ip_address = false
    security_groups             = [aws_security_group.ec2.id]
  }

  user_data = base64encode(local.cloud_init_prod)

  tag_specifications {
    resource_type = "instance"
    tags          = { Name = "tda-prod", Env = "prod" }
  }
}

# Staging EC2 instance (single, no ASG)
resource "aws_instance" "staging" {
  ami                    = data.aws_ami.cloudlinux.id
  instance_type          = var.ec2_instance_type
  subnet_id              = aws_subnet.private[0].id
  vpc_security_group_ids = [aws_security_group.ec2.id]
  iam_instance_profile   = aws_iam_instance_profile.ec2.name
  key_name               = aws_key_pair.main.key_name
  user_data              = local.cloud_init_staging

  tags = { Name = "tda-staging", Env = "staging" }
}
