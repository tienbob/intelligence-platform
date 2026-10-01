class CreateAuthThrottles < ActiveRecord::Migration[8.0]
  def change
    create_table :auth_throttles, id: false do |t|
      t.string :key, primary_key: true, limit: 64
      t.integer :attempts, null: false, default: 1
      t.datetime :expires_at, null: false
    end
    add_index :auth_throttles, :expires_at
  end
end
