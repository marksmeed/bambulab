resource "aws_autoscaling_group" "prod" {
  name                = "tda-asg-prod"
  min_size            = var.asg_min
  max_size            = var.asg_max
  desired_capacity    = var.asg_desired
  vpc_zone_identifier = aws_subnet.private[*].id
  target_group_arns   = [aws_lb_target_group.prod.arn]
  health_check_type   = "ELB"

  launch_template {
    id      = aws_launch_template.prod.id
    version = "$Latest"
  }

  instance_refresh {
    strategy = "Rolling"
    preferences {
      min_healthy_percentage = 50
    }
  }

  tag {
    key                 = "Name"
    value               = "tda-prod"
    propagate_at_launch = true
  }

  tag {
    key                 = "Env"
    value               = "prod"
    propagate_at_launch = true
  }
}

# Scale out when CPU > 70%
resource "aws_autoscaling_policy" "scale_out" {
  name                   = "tda-scale-out"
  autoscaling_group_name = aws_autoscaling_group.prod.name
  adjustment_type        = "ChangeInCapacity"
  scaling_adjustment     = 1
  cooldown               = 300
}

resource "aws_cloudwatch_metric_alarm" "cpu_high" {
  alarm_name          = "tda-cpu-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "CPUUtilization"
  namespace           = "AWS/EC2"
  period              = 120
  statistic           = "Average"
  threshold           = 70

  dimensions = {
    AutoScalingGroupName = aws_autoscaling_group.prod.name
  }

  alarm_actions = [aws_autoscaling_policy.scale_out.arn]
}

# Scale in when CPU < 30%
resource "aws_autoscaling_policy" "scale_in" {
  name                   = "tda-scale-in"
  autoscaling_group_name = aws_autoscaling_group.prod.name
  adjustment_type        = "ChangeInCapacity"
  scaling_adjustment     = -1
  cooldown               = 300
}

resource "aws_cloudwatch_metric_alarm" "cpu_low" {
  alarm_name          = "tda-cpu-low"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 2
  metric_name         = "CPUUtilization"
  namespace           = "AWS/EC2"
  period              = 120
  statistic           = "Average"
  threshold           = 30

  dimensions = {
    AutoScalingGroupName = aws_autoscaling_group.prod.name
  }

  alarm_actions = [aws_autoscaling_policy.scale_in.arn]
}
