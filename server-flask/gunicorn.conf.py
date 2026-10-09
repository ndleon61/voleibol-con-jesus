import os

port = int(os.environ.get("PORT", "8000"))
if not 1 <= port <= 65535:
    raise RuntimeError("PORT debe ser un puerto válido.")
bind = f"0.0.0.0:{port}" if "PORT" in os.environ else "127.0.0.1:8000"
workers = 2
worker_class = "sync"
timeout = 45
graceful_timeout = 45
max_requests = 1000
max_requests_jitter = 100
limit_request_line = 4094
limit_request_fields = 50
limit_request_field_size = 4094
accesslog = None
errorlog = "-"
capture_output = False
# Only ProxyFix may trust a specifically configured, isolated proxy.
forwarded_allow_ips = ""

if os.environ.get("APP_ENV") != "production":
    raise RuntimeError("Configura APP_ENV=production antes de iniciar Gunicorn.")
