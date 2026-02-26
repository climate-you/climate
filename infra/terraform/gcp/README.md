# GCP VM Terraform (V1)

This Terraform module provisions a single Ubuntu 24.04 VM with a static public IP and firewall rules for `22`, `80`, and `443`.

## Usage

```bash
cd infra/terraform/gcp
cp terraform.tfvars.example terraform.tfvars
# edit terraform.tfvars
terraform init
terraform plan
terraform apply
```

## Outputs

- `public_ip`
- `instance_name`
- `instance_zone`

## Next step

After `terraform apply`, SSH to the VM, clone this repository, and run:

```bash
sudo ./scripts/deploy/bootstrap_vm.sh --domain <your-domain> --repo-url <your-repo-url> --repo-branch main
```
