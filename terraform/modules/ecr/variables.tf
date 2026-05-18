variable "repository_name" {
  description = "ECR repository name"
  type        = string
  default     = "kagent-healer"
}

variable "tags" {
  description = "Tags applied to the ECR repository"
  type        = map(string)
  default     = {}
}
