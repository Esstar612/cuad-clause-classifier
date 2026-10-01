// The Cloud Run URL, set after the first deploy; a page opened from this machine uses the local service.
window.API_URL = ["localhost", "127.0.0.1"].includes(location.hostname) ? `http://${location.hostname}:8000` : "";
