terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
}

# CloudFront requires ACM certs in us-east-1
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
}

data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_ami" "cloudlinux" {
  most_recent = true
  owners      = ["679593333241"]

  filter {
    name   = "name"
    values = ["cloudlinux-10*-amd64.nopanel*"]
  }

  filter {
    name   = "state"
    values = ["available"]
  }
}
