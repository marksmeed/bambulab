variable "region" {
  default = "eu-west-1"
}

variable "domain" {
  default = "traindriversacademy.co.uk"
}

variable "environments" {
  default = ["prod", "staging"]
}

variable "ec2_instance_type" {
  default = "t3.medium"
}

variable "rds_instance_class" {
  default = "db.t3.medium"
}

variable "asg_min" {
  default = 1
}

variable "asg_max" {
  default = 3
}

variable "asg_desired" {
  default = 1
}

variable "db_name" {
  default = "joomla"
}

variable "db_username" {
  default = "joomla_admin"
}

variable "db_password" {
  description = "RDS master password"
  sensitive   = true
}
