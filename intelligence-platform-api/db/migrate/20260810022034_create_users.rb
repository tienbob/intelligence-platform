class CreateUsers < ActiveRecord::Migration[8.0]
  def change
    # Matches the existing Python/FastAPI `users` schema exactly
    # (app/models/user.py) so Rails can adopt ownership of the
    # shared database table.
    create_table :users, id: :bigint do |t|
      t.string  :email,         null: false, limit: 255
      t.string  :password_hash, null: false, limit: 255
      t.string  :name,          null: false, limit: 100
      t.string  :role,          null: false, limit: 20, default: "USER"
      t.boolean :is_active,     null: false, default: true

      t.timestamps
    end

    add_index :users, :email, unique: true
  end
end