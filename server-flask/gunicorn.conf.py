import os

bind = "127.0.0.1:8000"
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
