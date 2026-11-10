-- Schema of the opsmemory database. Written for an empty database.
-- Statements are separated by a line that holds only the marker used below.
-- Roles get their login secrets from scripts/apply_schema.py, never from this file.

CREATE ROLE agent_writer LOGIN
-- @@ --
CREATE ROLE approver LOGIN
-- @@ --
CREATE TABLE installations (
    installation_id text PRIMARY KEY,
    name            text NOT NULL
)
-- @@ --
CREATE TABLE services (
    installation_id text NOT NULL REFERENCES installations (installation_id),
    service_id      text NOT NULL,
    name            text NOT NULL,
    PRIMARY KEY (installation_id, service_id)
)
-- @@ --
CREATE TABLE source_fields (
    installation_id text    NOT NULL,
    service_id      text    NOT NULL,
    field_name      text    NOT NULL,
    unit            text    NOT NULL,
    min_sample_s    integer NOT NULL,
    max_sample_s    integer NOT NULL,
    PRIMARY KEY (installation_id, field_name),
    UNIQUE (installation_id, field_name, unit),
    UNIQUE (installation_id, service_id, field_name),
    FOREIGN KEY (installation_id) REFERENCES installations (installation_id),
    FOREIGN KEY (installation_id, service_id) REFERENCES services (installation_id, service_id)
)
-- @@ --
CREATE TABLE signal_requests (
    installation_id text    NOT NULL,
    request_id      text    NOT NULL,
    service_id      text    NOT NULL,
    signal_type     text    NOT NULL,
    sample_s        integer NOT NULL,
    request_text    text    NOT NULL,
    PRIMARY KEY (installation_id, request_id),
    UNIQUE (installation_id, request_id, service_id),
    UNIQUE (installation_id, request_id, signal_type),
    UNIQUE (installation_id, request_id, sample_s),
    FOREIGN KEY (installation_id, service_id) REFERENCES services (installation_id, service_id)
)
-- @@ --
CREATE TABLE allowed_units (
    signal_type text NOT NULL,
    unit        text NOT NULL,
    PRIMARY KEY (signal_type, unit)
)
-- @@ --
CREATE TABLE collection_configs (
    config_id       SERIAL PRIMARY KEY,
    run_id          text    NOT NULL,
    installation_id text    NOT NULL,
    request_id      text    NOT NULL,
    service_id      text    NOT NULL,
    signal_name     text    NOT NULL,
    signal_type     text    NOT NULL,
    source_field    text    NOT NULL,
    unit            text    NOT NULL,
    sample_s        integer NOT NULL,
    model_id        text    NOT NULL,
    status          text    NOT NULL DEFAULT 'draft',
    created_by      text    NOT NULL DEFAULT current_user,
    approved_by     text,
    is_bait         boolean NOT NULL DEFAULT false,

    CONSTRAINT collection_configs_signal_name_check
        CHECK (signal_name ~ '^[a-z][a-z0-9_]{2,40}$'),
    CONSTRAINT collection_configs_status_check
        CHECK (status IN ('draft', 'needs_review', 'approved', 'rejected', 'active')),
    CONSTRAINT config_approval_signed
        CHECK (status NOT IN ('approved', 'active') OR approved_by IS NOT NULL),

    CONSTRAINT config_one_per_request UNIQUE (run_id, installation_id, request_id),
    CONSTRAINT config_one_per_signal  UNIQUE (run_id, installation_id, signal_name),
    CONSTRAINT config_one_per_field   UNIQUE (run_id, installation_id, source_field),

    CONSTRAINT config_field_exists FOREIGN KEY (installation_id, source_field)
        REFERENCES source_fields (installation_id, field_name),
    CONSTRAINT config_unit_matches_source FOREIGN KEY (installation_id, source_field, unit)
        REFERENCES source_fields (installation_id, field_name, unit),
    CONSTRAINT config_answers_request FOREIGN KEY (installation_id, request_id)
        REFERENCES signal_requests (installation_id, request_id),
    CONSTRAINT config_service_matches_request FOREIGN KEY (installation_id, request_id, service_id)
        REFERENCES signal_requests (installation_id, request_id, service_id),
    CONSTRAINT config_field_in_service FOREIGN KEY (installation_id, service_id, source_field)
        REFERENCES source_fields (installation_id, service_id, field_name),
    CONSTRAINT config_type_matches_request FOREIGN KEY (installation_id, request_id, signal_type)
        REFERENCES signal_requests (installation_id, request_id, signal_type),
    CONSTRAINT config_sampling_requested FOREIGN KEY (installation_id, request_id, sample_s)
        REFERENCES signal_requests (installation_id, request_id, sample_s),
    CONSTRAINT config_unit_allowed_for_type FOREIGN KEY (signal_type, unit)
        REFERENCES allowed_units (signal_type, unit)
)
-- @@ --
CREATE TABLE review_log (
    config_id     integer     NOT NULL REFERENCES collection_configs (config_id),
    reviewer      text        NOT NULL DEFAULT current_user,
    verdict       text        NOT NULL CHECK (verdict IN ('approved', 'rejected')),
    bait_expected text        CHECK (bait_expected IN ('approved', 'rejected')),
    reviewed_at   timestamptz NOT NULL DEFAULT now()
)
-- @@ --
CREATE TABLE signals (
    installation_id text             NOT NULL,
    signal_name     text             NOT NULL,
    ts              timestamptz      NOT NULL,
    value           double precision NOT NULL,
    PRIMARY KEY (installation_id, signal_name, ts)
)
-- @@ --
INSERT INTO allowed_units (signal_type, unit) VALUES ('latency', 'ms')
-- @@ --
INSERT INTO allowed_units (signal_type, unit) VALUES ('latency', 's')
-- @@ --
INSERT INTO allowed_units (signal_type, unit) VALUES ('ratio', 'percent')
-- @@ --
INSERT INTO allowed_units (signal_type, unit) VALUES ('count', 'count')
-- @@ --
INSERT INTO allowed_units (signal_type, unit) VALUES ('age', 's')
-- @@ --
CREATE FUNCTION check_sampling() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    lo integer;
    hi integer;
BEGIN
    IF NEW.sample_s IS NULL THEN
        RETURN NEW;
    END IF;
    SELECT min_sample_s, max_sample_s INTO lo, hi
      FROM source_fields
     WHERE installation_id = NEW.installation_id AND field_name = NEW.source_field;
    IF NOT FOUND THEN
        RETURN NEW;
    END IF;
    IF NEW.sample_s < lo OR NEW.sample_s > hi THEN
        RAISE EXCEPTION 'config_sampling_supported: sample_s % outside % to % for %',
              NEW.sample_s, lo, hi, NEW.source_field
              USING ERRCODE = '23514', CONSTRAINT = 'config_sampling_supported';
    END IF;
    RETURN NEW;
END
$$
-- @@ --
CREATE TRIGGER config_sampling
BEFORE INSERT OR UPDATE OF source_field, sample_s ON collection_configs
FOR EACH ROW EXECUTE FUNCTION check_sampling()
-- @@ --
CREATE FUNCTION check_transition() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.status = OLD.status THEN
        RETURN NEW;
    END IF;
    IF current_user = 'agent_writer' AND NOT (OLD.status = 'draft' AND NEW.status = 'needs_review') THEN
        RAISE EXCEPTION 'config_agent_cannot_approve: agent cannot move a configuration from % to %',
              OLD.status, NEW.status
              USING ERRCODE = '42501', CONSTRAINT = 'config_agent_cannot_approve';
    END IF;
    IF NEW.status = 'active' AND OLD.status <> 'approved' THEN
        RAISE EXCEPTION 'config_promote_only_approved: only approved configurations become active'
              USING ERRCODE = '23514', CONSTRAINT = 'config_promote_only_approved';
    END IF;
    IF NEW.status = 'active' AND NEW.is_bait THEN
        RAISE EXCEPTION 'config_bait_never_active: bait configurations never become active'
              USING ERRCODE = '23514', CONSTRAINT = 'config_bait_never_active';
    END IF;
    RETURN NEW;
END
$$
-- @@ --
CREATE TRIGGER config_transition
BEFORE UPDATE ON collection_configs
FOR EACH ROW EXECUTE FUNCTION check_transition()
-- @@ --
CREATE FUNCTION check_signal_active() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM collection_configs
                    WHERE installation_id = NEW.installation_id
                      AND signal_name = NEW.signal_name
                      AND status = 'active') THEN
        RAISE EXCEPTION 'signal_needs_active_config: no active configuration for %', NEW.signal_name
              USING ERRCODE = '23503', CONSTRAINT = 'signal_needs_active_config';
    END IF;
    RETURN NEW;
END
$$
-- @@ --
CREATE TRIGGER signal_active
BEFORE INSERT ON signals
FOR EACH ROW EXECUTE FUNCTION check_signal_active()
-- @@ --
GRANT SELECT ON installations, services, source_fields, signal_requests, allowed_units, signals TO agent_writer
-- @@ --
GRANT INSERT (run_id, installation_id, request_id, service_id, signal_name, signal_type, source_field, unit, sample_s, model_id)
    ON collection_configs TO agent_writer
-- @@ --
GRANT SELECT ON collection_configs TO agent_writer
-- @@ --
GRANT UPDATE (status) ON collection_configs TO agent_writer
-- @@ --
GRANT USAGE ON SEQUENCE collection_configs_config_id_seq TO agent_writer
-- @@ --
GRANT SELECT ON collection_configs TO approver
-- @@ --
GRANT UPDATE (status, approved_by) ON collection_configs TO approver
-- @@ --
GRANT INSERT, SELECT ON review_log TO approver
