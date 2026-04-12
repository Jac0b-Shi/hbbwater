CREATE TABLE webhook_groups (
    id INT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description CLOB,
    webhook_token VARCHAR(64) NOT NULL,
    is_active SMALLINT DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uk_webhook_groups_token UNIQUE (webhook_token)
);

CREATE SEQUENCE seq_webhook_groups_id START WITH 1 INCREMENT BY 1;

CREATE OR REPLACE TRIGGER tri_webhook_groups_id
BEFORE INSERT ON webhook_groups
FOR EACH ROW
BEGIN
    IF :NEW.id IS NULL THEN
        SELECT seq_webhook_groups_id.NEXTVAL INTO :NEW.id;
    END IF;
END;
/

ALTER TABLE sensors
    ADD CONSTRAINT fk_sensors_webhook_group
    FOREIGN KEY (webhook_group_id) REFERENCES webhook_groups(id);

CREATE TABLE admin_users (
    id INT IDENTITY(1,1) PRIMARY KEY,
    username VARCHAR(50) NOT NULL,
    display_name VARCHAR(50) NOT NULL,
    email VARCHAR(255) NOT NULL,
    phone VARCHAR(32) DEFAULT '',
    "ROLE" VARCHAR(50) DEFAULT 'admin',
    password_hash VARCHAR(255) DEFAULT '',
    auth_provider VARCHAR(32) DEFAULT 'local',
    external_subject VARCHAR(128),
    is_active SMALLINT DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uk_admin_users_username UNIQUE (username),
    CONSTRAINT uk_admin_users_email UNIQUE (email)
);

CREATE INDEX idx_admin_users_auth_provider ON admin_users (auth_provider);
CREATE INDEX idx_admin_users_external_subject ON admin_users (external_subject);

INSERT INTO system_config (config_key, config_value, description, updated_at)
SELECT 'data_retention_days', '14', 'retention days', CURRENT_TIMESTAMP FROM dual
WHERE NOT EXISTS (SELECT 1 FROM system_config WHERE config_key = 'data_retention_days');

INSERT INTO system_config (config_key, config_value, description, updated_at)
SELECT 'account_provider', 'local', 'account provider', CURRENT_TIMESTAMP FROM dual
WHERE NOT EXISTS (SELECT 1 FROM system_config WHERE config_key = 'account_provider');

INSERT INTO system_config (config_key, config_value, description, updated_at)
SELECT 'account_local_username', 'admin', 'local username', CURRENT_TIMESTAMP FROM dual
WHERE NOT EXISTS (SELECT 1 FROM system_config WHERE config_key = 'account_local_username');

INSERT INTO system_config (config_key, config_value, description, updated_at)
SELECT 'account_local_display_name', 'admin', 'local display name', CURRENT_TIMESTAMP FROM dual
WHERE NOT EXISTS (SELECT 1 FROM system_config WHERE config_key = 'account_local_display_name');

INSERT INTO system_config (config_key, config_value, description, updated_at)
SELECT 'account_local_phone', '', 'local phone', CURRENT_TIMESTAMP FROM dual
WHERE NOT EXISTS (SELECT 1 FROM system_config WHERE config_key = 'account_local_phone');

INSERT INTO system_config (config_key, config_value, description, updated_at)
SELECT 'account_local_role', 'admin', 'local role', CURRENT_TIMESTAMP FROM dual
WHERE NOT EXISTS (SELECT 1 FROM system_config WHERE config_key = 'account_local_role');

INSERT INTO admin_users (
    username, display_name, email, phone, "ROLE",
    password_hash, auth_provider, is_active, created_at, updated_at
)
SELECT
    'admin', 'admin', 'admin@example.com', '', 'admin',
    '', 'local', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
FROM dual
WHERE NOT EXISTS (SELECT 1 FROM admin_users WHERE username = 'admin');
