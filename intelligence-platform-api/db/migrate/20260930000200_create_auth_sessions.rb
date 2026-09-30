class CreateAuthSessions < ActiveRecord::Migration[8.0]
  def change
    create_table :auth_sessions, id: :uuid do |t|
      t.bigint :user_id, null: false
      t.string :refresh_digest, null: false, limit: 64
      t.datetime :expires_at, null: false
      t.datetime :revoked_at
      t.timestamps
    end
    add_index :auth_sessions, :user_id
    add_index :auth_sessions, :expires_at
  end
end
