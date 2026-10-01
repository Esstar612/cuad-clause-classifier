// The review API on Cloud Run; a page opened from this machine uses the local service instead.
window.API_URL = ["localhost", "127.0.0.1"].includes(location.hostname)
  ? `http://${location.hostname}:8000`
  : "https://clause-review-api-128190849177.us-central1.run.app";
