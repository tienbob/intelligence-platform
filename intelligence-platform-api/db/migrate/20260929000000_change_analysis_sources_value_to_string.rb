class ChangeAnalysisSourcesValueToString < ActiveRecord::Migration[8.0]
  # Mirrors Python Alembic 0017 (shared DB, dual migration history).
  # LLM claim values are not always numeric (e.g. ceo_transition values),
  # so the column stores values verbatim as strings.
  def up
    return unless column_exists?(:analysis_sources, :value)
    change_column :analysis_sources, :value, :string, limit: 100
  end

  def down
    return unless column_exists?(:analysis_sources, :value)
    change_column :analysis_sources, :value, :float
  end
end