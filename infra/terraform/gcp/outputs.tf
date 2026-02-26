output "instance_name" {
  value = google_compute_instance.vm.name
}

output "instance_zone" {
  value = google_compute_instance.vm.zone
}

output "public_ip" {
  value = google_compute_address.public_ip.address
}
