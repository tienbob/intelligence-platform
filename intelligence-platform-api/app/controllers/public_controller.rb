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

  def metrics
    render_python(:get, "/metrics")
  end

  private

  def render_python(method, path)
    data = PythonClient.public_send(method, path)
    render json: data, status: :ok
  rescue PythonClient::PythonError => e
    render json: { detail: e.body }, status: e.status
  end
end