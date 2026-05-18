variable "cluster_name" {
  description = "EKS cluster name (used for subnet tagging)"
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "enable_ha_nat" {
  description = "Provision one NAT GW per AZ when true, otherwise a single shared NAT GW"
  type        = bool
  default     = false
}

variable "tags" {
  description = "Tags applied to all VPC resources"
  type        = map(string)
  default     = {}
}
