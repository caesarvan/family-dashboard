FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data PYTHONTZPATH=""
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd -u 10001 -m dashboard && mkdir /data && chown dashboard:dashboard /data
COPY app.py frontend_runtime.py member_sessions.py household_members.py tv_display.py sync_health.py ./
COPY household_memberships.py personal_accounts.py membership_storage.py membership_http.py ./
COPY cloud_accounts.py cloud_providers.py sync_worker.py ./
COPY google_photos_picker.py media_crypto.py media_images.py household_media.py media_import_worker.py media_playback.py ./
COPY shopping_media.py shopping_settlement.py finance_baseline.py spending_observations.py ./
COPY finance_source_bridge.py finance_accounts.py journey_time.py journey_reschedule.py ./
COPY household_spaces.py journey_workflows.py finance_hub.py home_assistant.py ./
COPY journey_documents.py journey_places.py ./
COPY inventory_core.py inventory_api.py inventory_sources.py ./
COPY calendar_publish.py financial_files.py investment_import.py investment_operations.py ./
COPY dashboard_preferences.py data_portability.py ./
COPY task_publish.py household_routines.py ./
COPY static ./static
USER dashboard
EXPOSE 8000
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "4", "--timeout", "45", "--access-logfile", "-", "--access-logformat", "%(h)s %(m)s %(U)s %(s)s", "app:create_app()"]
