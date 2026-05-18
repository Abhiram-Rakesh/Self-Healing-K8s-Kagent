variable "cluster_name" {
  description = "EKS cluster name"
  type        = string
}

variable "cluster_version" {
  description = "Kubernetes version for the EKS control plane"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID for the EKS cluster"
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs for the node groups"
  type        = list(string)
}

variable "public_subnet_ids" {
  description = "Public subnet IDs (for control plane ENIs and public ELBs)"
  type        = list(string)
}

variable "system_node_type" {
  description = "EC2 instance type for the system node group"
  type        = string
}

variable "system_node_count" {
  description = "Desired size of the system node group"
  type        = number
}

variable "workload_node_type" {
  description = "EC2 instance type for the workload node group"
  type        = string
}

variable "workload_node_count" {
  description = "Desired size of the workload node group"
  type        = number
}

variable "tags" {
  description = "Tags applied to all EKS resources"
  type        = map(string)
  default     = {}
}
