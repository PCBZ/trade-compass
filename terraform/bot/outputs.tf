output "bot_url" {
  description = "Cloud Run bot service URL (use as Telegram webhook URL)"
  value       = google_cloud_run_v2_service.bot.uri
}
