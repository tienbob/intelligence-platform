# frozen_string_literal: true

# Public health/metrics endpoints, proxied to the Python service so the
# public surface stays single (frontend → Rails → Python).
class PublicController < ActionController::API
  def health_live
    render_python(:get, "/health/live")
  end

  def health_ready
    render_python(:get, "/health/ready")
  end

  def health
    render_python(:get, "/health")
  end

  # Metrics expose traffic patterns, so they are NOT public (audit S02):
  # outside development the caller must present the internal service key.
  # nginx no longer proxies this path, so it is not reachable from the
  # internet at all.
  def metrics
    unless Rails.env.development? || metrics_authorized?
      render json: { detail: "Metrics require the internal service key" }, status: :unauthorized
      return
    end
    render_python(:get, "/metrics")
  end

  private

  def metrics_authorized?
    provided = request.headers["X-Service-Key"] || request.headers["X-API-Key"]
    return false if provided.blank?

    ActiveSupport::SecurityUtils.secure_compare(provided.to_s, Gateway::PYTHON_SERVICE_KEY)
  end

  def render_python(method, path)
    data = PythonClient.public_send(method, path)
    render json: data, status: :ok
  rescue PythonClient::PythonError => e
    render json: { detail: e.body }, status: e.status
  end
end